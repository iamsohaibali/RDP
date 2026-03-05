let activeJobId = null;
let pollTimer = null;
let selectedFields = [];

const statusText = document.getElementById('statusText');
const bar = document.getElementById('bar');
const rowsEl = document.getElementById('rows');
const headerRow = document.getElementById('headerRow');
const exportsEl = document.getElementById('exports');
const startBtn = document.getElementById('startBtn');
const stopBtn = document.getElementById('stopBtn');

async function initFields() {
  const res = await fetch('/api/fields');
  const data = await res.json();
  const wrap = document.getElementById('fields');
  wrap.innerHTML = '';
  data.fields.forEach((f) => {
    const id = `field_${f.key}`;
    const label = document.createElement('label');
    label.innerHTML = `<input checked type="checkbox" id="${id}" value="${f.key}"/> ${f.label}`;
    wrap.appendChild(label);
  });
}

function gatherSelectedFields() {
  return Array.from(document.querySelectorAll('#fields input[type="checkbox"]'))
    .filter((cb) => cb.checked)
    .map((cb) => cb.value);
}

function renderTable(rows) {
  rowsEl.innerHTML = '';
  headerRow.innerHTML = '';
  selectedFields.forEach((field) => {
    const th = document.createElement('th');
    th.innerText = field;
    headerRow.appendChild(th);
  });

  rows.slice(0, 100).forEach((row) => {
    const tr = document.createElement('tr');
    selectedFields.forEach((field) => {
      const td = document.createElement('td');
      td.innerText = row[field] ?? '';
      tr.appendChild(td);
    });
    rowsEl.appendChild(tr);
  });
}

async function pollStatus() {
  if (!activeJobId) return;
  const res = await fetch(`/api/status/${activeJobId}`);
  const data = await res.json();

  const total = data.total || 1;
  const pct = Math.min(100, (data.extracted / total) * 100);
  statusText.innerText = `${data.status.toUpperCase()} - ${data.extracted}/${data.total} (${data.message || ''})`;
  bar.style.width = `${pct}%`;
  renderTable(data.rows || []);

  exportsEl.innerHTML = '';
  if (data.csv) {
    exportsEl.innerHTML += `<a href="${data.csv}">Download CSV</a>`;
  }
  if (data.json) {
    exportsEl.innerHTML += `<a href="${data.json}">Download JSON</a>`;
  }

  if (['completed', 'failed', 'stopped'].includes(data.status)) {
    clearInterval(pollTimer);
    pollTimer = null;
    startBtn.disabled = false;
    stopBtn.disabled = true;
  }
}

startBtn.onclick = async () => {
  selectedFields = gatherSelectedFields();
  const payload = {
    keyword: document.getElementById('keyword').value,
    location: document.getElementById('location').value,
    max_results: Number(document.getElementById('maxResults').value),
    fields: selectedFields,
    sheet_url: document.getElementById('sheetUrl').value || null,
    credentials_path: document.getElementById('credsPath').value || null,
  };

  const res = await fetch('/api/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    statusText.innerText = 'Failed to start job';
    return;
  }

  const data = await res.json();
  activeJobId = data.job_id;
  startBtn.disabled = true;
  stopBtn.disabled = false;
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(pollStatus, 2000);
};

stopBtn.onclick = async () => {
  if (!activeJobId) return;
  await fetch(`/api/stop/${activeJobId}`, { method: 'POST' });
};

document.getElementById('scheduleBtn').onclick = async () => {
  const payload = {
    keyword: document.getElementById('keyword').value,
    location: document.getElementById('location').value,
    max_results: Number(document.getElementById('maxResults').value),
    fields: gatherSelectedFields(),
    sheet_url: document.getElementById('sheetUrl').value || null,
    credentials_path: document.getElementById('credsPath').value || null,
    run_time_utc: document.getElementById('runTime').value,
  };

  const res = await fetch('/api/schedule', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (res.ok) {
    statusText.innerText = 'Daily schedule created.';
  } else {
    statusText.innerText = 'Failed to schedule. Use HH:MM UTC format.';
  }
};

initFields();
