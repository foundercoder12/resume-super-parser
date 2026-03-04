"""
GET /dashboard  — HTML monitoring dashboard.
Fetches data from GET /v1/metrics and renders it client-side.
No external JS/CSS libraries — pure HTML + SVG + vanilla JS.
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Resume Parser — Monitoring</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #f0f2f5; color: #1a1a2e; font-size: 14px;
    }

    /* ── Header ── */
    header {
      background: #1a1a2e; color: #fff; padding: 16px 32px;
      display: flex; align-items: center; justify-content: space-between;
    }
    header h1 { font-size: 1.2rem; font-weight: 600; letter-spacing: .02em; }
    header h1 span { color: #818cf8; }
    #refresh-info { font-size: .75rem; color: #94a3b8; }

    /* ── Layout ── */
    .page { max-width: 1280px; margin: 0 auto; padding: 28px 24px; }
    .section-title {
      font-size: .7rem; font-weight: 700; letter-spacing: .1em;
      text-transform: uppercase; color: #6b7280; margin: 28px 0 12px;
    }

    /* ── KPI cards ── */
    .kpi-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
      gap: 14px;
    }
    .kpi {
      background: #fff; border-radius: 12px; padding: 18px 20px;
      box-shadow: 0 1px 4px rgba(0,0,0,.07);
    }
    .kpi .label { font-size: .72rem; color: #6b7280; margin-bottom: 8px; font-weight: 500; }
    .kpi .value { font-size: 1.8rem; font-weight: 700; line-height: 1; }
    .kpi .sub   { font-size: .75rem; color: #9ca3af; margin-top: 4px; }
    .kpi.green .value  { color: #16a34a; }
    .kpi.red .value    { color: #dc2626; }
    .kpi.blue .value   { color: #2563eb; }
    .kpi.amber .value  { color: #d97706; }
    .kpi.purple .value { color: #7c3aed; }
    .kpi.teal .value   { color: #0d9488; }

    /* ── Two-column row ── */
    .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    @media (max-width: 720px) { .two-col { grid-template-columns: 1fr; } }

    /* ── Card ── */
    .card {
      background: #fff; border-radius: 12px; padding: 22px 24px;
      box-shadow: 0 1px 4px rgba(0,0,0,.07);
    }
    .card h3 {
      font-size: .8rem; font-weight: 700; letter-spacing: .08em;
      text-transform: uppercase; color: #6b7280; margin-bottom: 16px;
    }

    /* ── Status bar ── */
    .status-bar-wrap { margin-bottom: 12px; }
    .status-bar {
      display: flex; height: 10px; border-radius: 99px; overflow: hidden;
      background: #e5e7eb; margin-bottom: 10px;
    }
    .status-bar .seg { height: 100%; transition: width .4s; }
    .seg.succeeded { background: #16a34a; }
    .seg.failed    { background: #dc2626; }
    .seg.pending   { background: #f59e0b; }
    .seg.running   { background: #2563eb; }
    .seg.duplicate { background: #8b5cf6; }
    .legend { display: flex; flex-wrap: wrap; gap: 10px; }
    .legend-item {
      display: flex; align-items: center; gap: 5px;
      font-size: .75rem; color: #374151;
    }
    .legend-dot {
      width: 8px; height: 8px; border-radius: 50%;
    }
    .dot-succeeded { background: #16a34a; }
    .dot-failed    { background: #dc2626; }
    .dot-pending   { background: #f59e0b; }
    .dot-running   { background: #2563eb; }
    .dot-duplicate { background: #8b5cf6; }

    /* ── Source type doughnut (CSS-only) ── */
    .donut-row { display: flex; align-items: center; gap: 24px; }
    .donut-legend { flex: 1; }
    .donut-legend-item {
      display: flex; align-items: center; justify-content: space-between;
      padding: 5px 0; border-bottom: 1px solid #f3f4f6; font-size: .82rem;
    }
    .donut-legend-item:last-child { border-bottom: none; }
    .donut-legend-item .name { display: flex; align-items: center; gap: 7px; }
    .donut-legend-item .dot {
      width: 9px; height: 9px; border-radius: 50%;
    }
    .dot-digital  { background: #6366f1; }
    .dot-scanned  { background: #f59e0b; }
    .dot-hybrid   { background: #10b981; }

    /* ── Daily bar chart ── */
    .bar-chart {
      display: flex; align-items: flex-end; gap: 4px;
      height: 80px; padding: 0 2px;
    }
    .bar-wrap {
      flex: 1; display: flex; flex-direction: column;
      align-items: center; gap: 3px; height: 100%;
    }
    .bar-inner {
      width: 100%; border-radius: 4px 4px 0 0; background: #818cf8;
      min-height: 2px; transition: height .3s;
    }
    .bar-date {
      font-size: .55rem; color: #9ca3af; white-space: nowrap;
      transform: rotate(-45deg) translateX(-4px); transform-origin: top right;
      max-width: 30px; overflow: hidden; text-overflow: ellipsis;
    }
    .chart-empty { color: #9ca3af; font-size: .82rem; padding: 20px 0; text-align: center; }

    /* ── Failure reasons ── */
    .reasons-list { list-style: none; }
    .reasons-list li {
      display: flex; align-items: center; justify-content: space-between;
      padding: 9px 0; border-bottom: 1px solid #f3f4f6; font-size: .83rem;
    }
    .reasons-list li:last-child { border-bottom: none; }
    .err-code {
      font-family: monospace; background: #fef2f2; color: #dc2626;
      padding: 2px 8px; border-radius: 4px; font-size: .78rem;
    }
    .count-badge {
      background: #f3f4f6; color: #374151; padding: 2px 10px;
      border-radius: 99px; font-weight: 600; font-size: .78rem;
    }
    .empty-msg { color: #9ca3af; font-size: .82rem; padding: 12px 0; }

    /* ── Recent jobs table ── */
    table { width: 100%; border-collapse: collapse; font-size: .82rem; }
    th {
      text-align: left; padding: 8px 12px; color: #6b7280;
      font-size: .7rem; font-weight: 600; letter-spacing: .07em;
      text-transform: uppercase; border-bottom: 2px solid #f3f4f6;
    }
    td { padding: 10px 12px; border-bottom: 1px solid #f9fafb; }
    tr:last-child td { border-bottom: none; }
    tr:hover td { background: #fafafa; }
    .badge {
      display: inline-block; padding: 2px 9px; border-radius: 99px;
      font-size: .72rem; font-weight: 600;
    }
    .badge-succeeded { background: #dcfce7; color: #16a34a; }
    .badge-failed    { background: #fee2e2; color: #dc2626; }
    .badge-pending   { background: #fef9c3; color: #92400e; }
    .badge-running   { background: #dbeafe; color: #1d4ed8; }
    .badge-duplicate { background: #ede9fe; color: #7c3aed; }
    .mono { font-family: monospace; color: #6b7280; font-size: .75rem; }
    .err  { font-family: monospace; color: #dc2626; font-size: .75rem; }

    /* ── Loader ── */
    #loader {
      position: fixed; inset: 0; background: rgba(240,242,245,.8);
      display: flex; align-items: center; justify-content: center; z-index: 99;
    }
    .spinner {
      width: 36px; height: 36px; border: 3px solid #e5e7eb;
      border-top-color: #6366f1; border-radius: 50%;
      animation: spin .7s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    #error-banner {
      display: none; background: #fef2f2; color: #dc2626;
      border: 1px solid #fecaca; border-radius: 8px; padding: 12px 20px;
      margin-bottom: 20px; font-size: .85rem;
    }
  </style>
</head>
<body>

<div id="loader"><div class="spinner"></div></div>

<header>
  <h1>Resume Parser <span>Monitoring</span></h1>
  <span id="refresh-info">Auto-refreshes every 30s</span>
</header>

<div class="page">
  <div id="error-banner"></div>

  <!-- KPIs -->
  <p class="section-title">Overview</p>
  <div class="kpi-grid">
    <div class="kpi">
      <div class="label">Total Parsed</div>
      <div class="value" id="kpi-total">—</div>
    </div>
    <div class="kpi green">
      <div class="label">Succeeded</div>
      <div class="value" id="kpi-succeeded">—</div>
      <div class="sub" id="kpi-success-rate">—</div>
    </div>
    <div class="kpi red">
      <div class="label">Failed</div>
      <div class="value" id="kpi-failed">—</div>
    </div>
    <div class="kpi blue">
      <div class="label">Avg Parse Time</div>
      <div class="value" id="kpi-parse-time">—</div>
      <div class="sub">seconds</div>
    </div>
    <div class="kpi purple">
      <div class="label">Avg Confidence</div>
      <div class="value" id="kpi-confidence">—</div>
      <div class="sub">out of 1.0</div>
    </div>
    <div class="kpi teal">
      <div class="label">Avg Cost / Parse</div>
      <div class="value" id="kpi-cost">—</div>
      <div class="sub">USD</div>
    </div>
    <div class="kpi amber">
      <div class="label">OCR Used</div>
      <div class="value" id="kpi-ocr-rate">—</div>
      <div class="sub" id="kpi-ocr-count">— parses</div>
    </div>
    <div class="kpi">
      <div class="label">Duplicates</div>
      <div class="value" id="kpi-duplicates">—</div>
      <div class="sub" id="kpi-dup-rate">—</div>
    </div>
  </div>

  <!-- Status distribution + Source type -->
  <p class="section-title">Breakdown</p>
  <div class="two-col">

    <div class="card">
      <h3>Job Status Distribution</h3>
      <div class="status-bar-wrap">
        <div class="status-bar" id="status-bar"></div>
        <div class="legend" id="status-legend"></div>
      </div>
    </div>

    <div class="card">
      <h3>PDF Source Type</h3>
      <div id="source-content"></div>
    </div>

  </div>

  <!-- Daily throughput + Failure reasons -->
  <p class="section-title">Trends & Errors</p>
  <div class="two-col">

    <div class="card">
      <h3>Daily Throughput (Last 30 Days)</h3>
      <div id="daily-chart"></div>
    </div>

    <div class="card">
      <h3>Failure Reasons</h3>
      <div id="failures-content"></div>
    </div>

  </div>

  <!-- Recent jobs -->
  <p class="section-title">Recent Jobs</p>
  <div class="card">
    <h3>Last 20 Jobs</h3>
    <div style="overflow-x:auto">
      <table>
        <thead>
          <tr>
            <th>Job ID</th>
            <th>Status</th>
            <th>Created</th>
            <th>Parse Time</th>
            <th>File Size</th>
            <th>Error</th>
          </tr>
        </thead>
        <tbody id="jobs-tbody"></tbody>
      </table>
    </div>
  </div>

</div>

<script>
  const STATUS_COLORS = {
    succeeded: '#16a34a', failed: '#dc2626',
    pending: '#f59e0b', running: '#2563eb', duplicate: '#8b5cf6'
  };

  function fmt(n, decimals = 0) {
    if (n == null) return '—';
    return typeof n === 'number' ? n.toFixed(decimals) : n;
  }

  function relativeTime(isoStr) {
    if (!isoStr) return '—';
    const diff = Math.floor((Date.now() - new Date(isoStr)) / 1000);
    if (diff < 60)  return diff + 's ago';
    if (diff < 3600) return Math.floor(diff/60) + 'm ago';
    if (diff < 86400) return Math.floor(diff/3600) + 'h ago';
    return Math.floor(diff/86400) + 'd ago';
  }

  function shortId(uuid) {
    return uuid ? uuid.slice(0, 8) + '…' : '—';
  }

  function render(data) {
    const s = data.summary;

    // KPIs
    document.getElementById('kpi-total').textContent      = s.total ?? '—';
    document.getElementById('kpi-succeeded').textContent  = s.succeeded ?? '—';
    document.getElementById('kpi-success-rate').textContent = s.success_rate != null ? s.success_rate + '%' : '—';
    document.getElementById('kpi-failed').textContent     = s.failed ?? '—';
    document.getElementById('kpi-parse-time').textContent = fmt(s.avg_parse_time_s, 1);
    document.getElementById('kpi-confidence').textContent = fmt(s.avg_confidence, 3);
    document.getElementById('kpi-cost').textContent       = s.avg_cost_usd != null ? '$' + s.avg_cost_usd.toFixed(5) : '—';
    document.getElementById('kpi-ocr-rate').textContent   = s.ocr_rate != null ? s.ocr_rate + '%' : '—';
    document.getElementById('kpi-ocr-count').textContent  = (s.ocr_count ?? '—') + ' parses';
    document.getElementById('kpi-duplicates').textContent = s.duplicate ?? '—';
    document.getElementById('kpi-dup-rate').textContent   = s.duplicate_rate != null ? s.duplicate_rate + '%' : '—';

    // Status bar
    const bar = document.getElementById('status-bar');
    const legend = document.getElementById('status-legend');
    bar.innerHTML = ''; legend.innerHTML = '';
    const total = s.total || 1;
    ['succeeded','failed','running','pending','duplicate'].forEach(st => {
      const n = s[st] || 0;
      const pct = (n / total * 100).toFixed(1);
      if (n > 0) {
        const seg = document.createElement('div');
        seg.className = 'seg ' + st;
        seg.style.width = pct + '%';
        seg.title = st + ': ' + n;
        bar.appendChild(seg);

        const li = document.createElement('div');
        li.className = 'legend-item';
        li.innerHTML = `<span class="legend-dot dot-${st}"></span><span>${st} (${n})</span>`;
        legend.appendChild(li);
      }
    });

    // Source type
    const src = data.source_breakdown || {};
    const srcTotal = Object.values(src).reduce((a,b)=>a+b, 0) || 1;
    const srcEl = document.getElementById('source-content');
    if (Object.keys(src).length === 0) {
      srcEl.innerHTML = '<p class="empty-msg">No data yet.</p>';
    } else {
      const dotClass = { digital:'dot-digital', scanned:'dot-scanned', hybrid:'dot-hybrid' };
      srcEl.innerHTML = '<div class="donut-legend">' +
        Object.entries(src).map(([type, cnt]) =>
          `<div class="donut-legend-item">
            <span class="name"><span class="dot ${dotClass[type] || 'dot-digital'}"></span>${type}</span>
            <span>${cnt} <small style="color:#9ca3af">(${(cnt/srcTotal*100).toFixed(0)}%)</small></span>
          </div>`
        ).join('') +
        '</div>';
    }

    // Daily bar chart
    const days = data.daily_throughput || [];
    const chartEl = document.getElementById('daily-chart');
    if (days.length === 0) {
      chartEl.innerHTML = '<p class="chart-empty">No data in last 30 days.</p>';
    } else {
      const maxN = Math.max(...days.map(d => d.count), 1);
      chartEl.innerHTML = '<div class="bar-chart">' +
        days.map(d => {
          const pct = Math.round((d.count / maxN) * 100);
          const label = d.date.slice(5); // MM-DD
          return `<div class="bar-wrap" title="${d.date}: ${d.count}">
            <div style="flex:1;display:flex;align-items:flex-end;width:100%">
              <div class="bar-inner" style="height:${pct}%"></div>
            </div>
            <div class="bar-date">${label}</div>
          </div>`;
        }).join('') +
        '</div>';
    }

    // Failure reasons
    const fails = data.failure_reasons || [];
    const failEl = document.getElementById('failures-content');
    if (fails.length === 0) {
      failEl.innerHTML = '<p class="empty-msg">No failures recorded.</p>';
    } else {
      failEl.innerHTML = '<ul class="reasons-list">' +
        fails.map(f =>
          `<li>
            <span class="err-code">${f.error_code}</span>
            <span class="count-badge">${f.count}</span>
          </li>`
        ).join('') +
        '</ul>';
    }

    // Recent jobs table
    const tbody = document.getElementById('jobs-tbody');
    const jobs = data.recent_jobs || [];
    if (jobs.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#9ca3af;padding:20px">No jobs yet.</td></tr>';
    } else {
      tbody.innerHTML = jobs.map(j => `
        <tr>
          <td class="mono" title="${j.job_id}">${shortId(j.job_id)}</td>
          <td><span class="badge badge-${j.status}">${j.status}</span></td>
          <td style="color:#6b7280">${relativeTime(j.created_at)}</td>
          <td>${j.parse_time_s != null ? j.parse_time_s + 's' : '—'}</td>
          <td style="color:#6b7280">${j.file_size_bytes ? (j.file_size_bytes/1024).toFixed(0)+'KB' : '—'}</td>
          <td class="err">${j.error_code || ''}</td>
        </tr>`
      ).join('');
    }
  }

  async function load() {
    try {
      const res = await fetch('/v1/metrics');
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      render(data);
      document.getElementById('error-banner').style.display = 'none';
    } catch(e) {
      const banner = document.getElementById('error-banner');
      banner.style.display = 'block';
      banner.textContent = 'Failed to load metrics: ' + e.message;
    } finally {
      document.getElementById('loader').style.display = 'none';
    }

    // Update refresh timestamp
    document.getElementById('refresh-info').textContent =
      'Last updated ' + new Date().toLocaleTimeString() + ' · auto-refreshes every 30s';
  }

  load();
  setInterval(load, 30_000);
</script>
</body>
</html>"""


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(_HTML)
