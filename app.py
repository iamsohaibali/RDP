import random
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from gspread import service_account
from pydantic import BaseModel, Field
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE_DIR = Path(__file__).resolve().parent
EXPORT_DIR = BASE_DIR / "exports"
EXPORT_DIR.mkdir(exist_ok=True)

DEFAULT_FIELDS = [
    "business_name",
    "address",
    "phone_number",
    "website",
    "rating",
    "total_reviews",
    "google_maps_url",
    "category",
]

HEADERS = {
    "business_name": "Business Name",
    "address": "Address",
    "phone_number": "Phone Number",
    "website": "Website",
    "rating": "Rating",
    "total_reviews": "Total Reviews",
    "google_maps_url": "Google Maps URL",
    "category": "Category",
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
]


class ScrapeRequest(BaseModel):
    keyword: str
    location: str
    max_results: int = Field(default=20, ge=1, le=500)
    fields: List[str] = Field(default_factory=lambda: DEFAULT_FIELDS.copy())
    sheet_url: Optional[str] = None
    credentials_path: Optional[str] = "google_service_account.json"


class ScheduleRequest(ScrapeRequest):
    run_time_utc: str = Field(..., description="HH:MM 24-hour UTC time")


@dataclass
class JobState:
    id: str
    status: str = "queued"
    extracted: int = 0
    total: int = 0
    message: str = ""
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    rows: List[Dict[str, Any]] = field(default_factory=list)
    output_csv: Optional[str] = None
    output_json: Optional[str] = None
    stop_requested: bool = False


app = FastAPI(title="Google Maps Business Extractor")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

jobs: Dict[str, JobState] = {}
scheduled_jobs: Dict[str, Dict[str, Any]] = {}
lock = threading.Lock()
scheduler = BackgroundScheduler(timezone="UTC")
scheduler.start()


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _extract_reviews_count(text: str) -> str:
    match = re.search(r"([\d,]+)", text or "")
    return match.group(1).replace(",", "") if match else ""


def _create_sheet_client(credentials_path: str):
    return service_account(filename=credentials_path)


def append_to_google_sheet(sheet_url: str, credentials_path: str, fields: List[str], rows: List[Dict[str, Any]]) -> None:
    gc = _create_sheet_client(credentials_path)
    sh = gc.open_by_url(sheet_url)
    worksheet = sh.sheet1

    existing_values = worksheet.get_all_values()
    expected_headers = [HEADERS[f] for f in fields]
    if not existing_values:
        worksheet.append_row(expected_headers)
    elif existing_values[0] != expected_headers:
        worksheet.update("A1", [expected_headers])

    batch_rows = [[row.get(field, "") for field in fields] for row in rows]
    if batch_rows:
        worksheet.append_rows(batch_rows, value_input_option="USER_ENTERED")


def scrape_google_maps(job: JobState, payload: ScrapeRequest) -> None:
    query = f"{payload.keyword} {payload.location}".strip()
    seen = set()
    data: List[Dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=random.choice(USER_AGENTS), locale="en-US")
        page = context.new_page()

        page.goto(f"https://www.google.com/maps/search/{query.replace(' ', '+')}", wait_until="domcontentloaded")
        page.wait_for_timeout(random.randint(2000, 3500))

        results_panel = "div[role='feed']"
        page.wait_for_selector(results_panel, timeout=20000)
        cards_selector = "a.hfpxzc"

        last_count = 0
        retries = 0
        while len(data) < payload.max_results and retries < 20:
            if job.stop_requested:
                break

            cards = page.locator(cards_selector)
            current_count = cards.count()

            if current_count == last_count:
                retries += 1
            else:
                retries = 0
                last_count = current_count

            for i in range(current_count):
                if len(data) >= payload.max_results or job.stop_requested:
                    break

                try:
                    card = cards.nth(i)
                    href = card.get_attribute("href") or ""
                    if not href or href in seen:
                        continue
                    seen.add(href)

                    card.click(timeout=7000)
                    page.wait_for_timeout(random.randint(1300, 2600))

                    name = _normalize(page.locator("h1.DUwDvf").inner_text(timeout=5000))
                    if not name:
                        continue

                    address = _normalize(page.locator("button[data-item-id='address'] div.fontBodyMedium").first.inner_text()) if page.locator("button[data-item-id='address'] div.fontBodyMedium").count() else ""
                    phone = _normalize(page.locator("button[data-item-id^='phone:tel:'] div.fontBodyMedium").first.inner_text()) if page.locator("button[data-item-id^='phone:tel:'] div.fontBodyMedium").count() else ""
                    website = page.locator("a[data-item-id='authority']").first.get_attribute("href") if page.locator("a[data-item-id='authority']").count() else ""
                    rating = _normalize(page.locator("div.F7nice span[aria-hidden='true']").first.inner_text()) if page.locator("div.F7nice span[aria-hidden='true']").count() else ""
                    review_text = _normalize(page.locator("div.F7nice span[aria-label*='reviews']").first.inner_text()) if page.locator("div.F7nice span[aria-label*='reviews']").count() else ""
                    total_reviews = _extract_reviews_count(review_text)
                    category = _normalize(page.locator("button.DkEaL").first.inner_text()) if page.locator("button.DkEaL").count() else ""

                    row = {
                        "business_name": name,
                        "address": address,
                        "phone_number": phone,
                        "website": website or "",
                        "rating": rating,
                        "total_reviews": total_reviews,
                        "google_maps_url": page.url,
                        "category": category,
                    }

                    data.append(row)
                    with lock:
                        job.rows = data.copy()
                        job.extracted = len(data)
                        job.status = "running"

                except PlaywrightTimeoutError:
                    continue
                except Exception:
                    continue

            page.locator(results_panel).evaluate("el => el.scrollBy(0, 2500)")
            page.wait_for_timeout(random.randint(1000, 2200))

        context.close()
        browser.close()

    df = pd.DataFrame(data)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    csv_path = EXPORT_DIR / f"{job.id}_{stamp}.csv"
    json_path = EXPORT_DIR / f"{job.id}_{stamp}.json"
    df.to_csv(csv_path, index=False)
    df.to_json(json_path, orient="records", indent=2)

    with lock:
        job.output_csv = str(csv_path)
        job.output_json = str(json_path)
        job.rows = data

    if payload.sheet_url and data:
        append_to_google_sheet(payload.sheet_url, payload.credentials_path or "google_service_account.json", payload.fields, data)


def run_job(job_id: str, payload: ScrapeRequest) -> None:
    with lock:
        job = jobs[job_id]
        job.status = "running"
        job.total = payload.max_results
        job.started_at = datetime.utcnow().isoformat()

    try:
        scrape_google_maps(job, payload)
        with lock:
            job.status = "stopped" if job.stop_requested else "completed"
            job.message = "Stopped by user." if job.stop_requested else "Extraction completed successfully."
            job.finished_at = datetime.utcnow().isoformat()
    except Exception as exc:
        with lock:
            job.status = "failed"
            job.message = str(exc)
            job.finished_at = datetime.utcnow().isoformat()


def enqueue_job(payload: ScrapeRequest) -> str:
    job_id = str(uuid.uuid4())
    with lock:
        jobs[job_id] = JobState(id=job_id)

    thread = threading.Thread(target=run_job, args=(job_id, payload), daemon=True)
    thread.start()
    return job_id


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (BASE_DIR / "static/index.html").read_text(encoding="utf-8")


@app.post("/api/start")
def start_scrape(payload: ScrapeRequest):
    invalid = [f for f in payload.fields if f not in DEFAULT_FIELDS]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Invalid fields: {invalid}")
    job_id = enqueue_job(payload)
    return {"job_id": job_id}


@app.post("/api/stop/{job_id}")
def stop_scrape(job_id: str):
    with lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        job.stop_requested = True
    return {"status": "stop_requested"}


@app.get("/api/status/{job_id}")
def get_status(job_id: str):
    with lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return {
            "id": job.id,
            "status": job.status,
            "message": job.message,
            "extracted": job.extracted,
            "total": job.total,
            "rows": job.rows,
            "csv": f"/api/export/csv/{job.id}" if job.output_csv else None,
            "json": f"/api/export/json/{job.id}" if job.output_json else None,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
        }


@app.get("/api/export/csv/{job_id}")
def export_csv(job_id: str):
    with lock:
        job = jobs.get(job_id)
        if not job or not job.output_csv:
            raise HTTPException(status_code=404, detail="CSV not available")
        return FileResponse(job.output_csv, filename=f"maps_{job_id}.csv")


@app.get("/api/export/json/{job_id}")
def export_json(job_id: str):
    with lock:
        job = jobs.get(job_id)
        if not job or not job.output_json:
            raise HTTPException(status_code=404, detail="JSON not available")
        return FileResponse(job.output_json, filename=f"maps_{job_id}.json")


@app.post("/api/schedule")
def schedule_scrape(payload: ScheduleRequest):
    if not re.fullmatch(r"^([01]\d|2[0-3]):([0-5]\d)$", payload.run_time_utc):
        raise HTTPException(status_code=400, detail="run_time_utc must be HH:MM in UTC")

    sched_id = str(uuid.uuid4())
    hour, minute = [int(x) for x in payload.run_time_utc.split(":")]

    def _scheduled_runner():
        enqueue_job(ScrapeRequest(**payload.model_dump(exclude={"run_time_utc"})))

    scheduler.add_job(_scheduled_runner, "cron", hour=hour, minute=minute, id=sched_id, replace_existing=True)
    scheduled_jobs[sched_id] = {
        "id": sched_id,
        "keyword": payload.keyword,
        "location": payload.location,
        "run_time_utc": payload.run_time_utc,
    }
    return {"scheduled_job_id": sched_id}


@app.get("/api/schedule")
def list_schedules():
    return {"schedules": list(scheduled_jobs.values())}


@app.delete("/api/schedule/{scheduled_job_id}")
def delete_schedule(scheduled_job_id: str):
    if scheduled_job_id not in scheduled_jobs:
        raise HTTPException(status_code=404, detail="Schedule not found")
    scheduler.remove_job(scheduled_job_id)
    scheduled_jobs.pop(scheduled_job_id, None)
    return {"status": "deleted"}


@app.get("/api/fields")
def list_fields():
    return {"fields": [{"key": k, "label": v} for k, v in HEADERS.items()]}
