# Google Maps Business Extractor → Google Sheets

A full-stack web tool that scrapes Google Maps business listings from user-defined search criteria and exports results to:
- Google Sheets (append mode)
- CSV download
- JSON download

Backend is **FastAPI + Playwright + Pandas + gspread**, with a simple dashboard UI and daily scheduling support.

## Features

- Search keyword + location query (`keyword + location`)
- User-defined max result count
- Field selection:
  - Business Name
  - Address
  - Phone Number
  - Website
  - Rating
  - Total Reviews
  - Google Maps URL
  - Category
- Start/Stop extraction jobs
- Live progress and preview table
- Duplicate filtering (by listing URL)
- Dynamic scrolling to load more results
- Random delays and user-agent rotation (basic anti-blocking strategy)
- Export result files (CSV/JSON)
- Google Sheets append integration with header management
- Daily schedule creation (UTC HH:MM)

## Project Structure

```text
RDP/
├── app.py                  # FastAPI backend, scraper, scheduler, export APIs
├── requirements.txt
├── README.md
├── exports/                # Generated CSV/JSON files
└── static/
    ├── index.html          # Dashboard UI
    ├── styles.css          # UI styles
    └── app.js              # Frontend logic + polling
```

## Prerequisites

- Python 3.10+
- Chromium dependencies (for Playwright)
- Google Cloud service account (for Sheets integration)

## Local Setup

1. **Clone & enter project**
   ```bash
   cd /workspace/RDP
   ```

2. **Create and activate virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

4. **Run server**
   ```bash
   uvicorn app:app --reload --host 0.0.0.0 --port 8000
   ```

5. **Open app**
   - `http://localhost:8000`

## Google Sheets API Configuration (gspread)

1. Go to Google Cloud Console.
2. Create/select a project.
3. Enable **Google Sheets API** and **Google Drive API**.
4. Create a **Service Account**.
5. Create a JSON key and download it.
6. Save it in project root as:
   - `google_service_account.json`
   - or any path you provide in the UI (`Credentials File`).
7. Open your target Google Sheet and share it with the service-account email (Editor access).
8. Paste the Google Sheet URL into the dashboard.

## How to Use

1. Enter keyword, location, and max results.
2. Select fields to extract.
3. Optionally add Google Sheet URL and credentials file path.
4. Click **Start Extraction**.
5. Monitor live progress and preview rows.
6. Download CSV/JSON when finished.
7. (Optional) Schedule a daily run using UTC time (`HH:MM`).

## API Endpoints

- `GET /` - dashboard UI
- `POST /api/start` - start extraction
- `POST /api/stop/{job_id}` - stop running extraction
- `GET /api/status/{job_id}` - job status + preview rows + export links
- `GET /api/export/csv/{job_id}` - CSV download
- `GET /api/export/json/{job_id}` - JSON download
- `POST /api/schedule` - create daily job
- `GET /api/schedule` - list schedules
- `DELETE /api/schedule/{scheduled_job_id}` - remove schedule
- `GET /api/fields` - available selectable fields

## Notes & Reliability

- Google Maps DOM may change over time; selectors may require maintenance.
- Scraping Google Maps can trigger rate-limits/challenges. Mitigations included:
  - randomized delays
  - user-agent rotation
  - controlled extraction pacing
- For larger-scale extraction, consider proxy rotation and robust queue persistence.

## Legal / Compliance

Ensure your usage complies with Google Maps terms of service and local laws.
