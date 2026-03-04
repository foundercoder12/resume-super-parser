"""
Simple frontend server for testing the resume parser pipeline.
No database or queue — runs the pipeline inline and returns results.

Usage: PYTHONPATH=. python3 frontend_server.py
Then open http://localhost:8080
"""
import asyncio
import json
import os
import tempfile
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
import cgi

# Load .env
from dotenv import load_dotenv
load_dotenv()


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Resume Parser</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f5f5; color: #333; }
    .container { max-width: 960px; margin: 40px auto; padding: 0 20px; }
    h1 { font-size: 1.8rem; font-weight: 700; margin-bottom: 8px; }
    p.sub { color: #666; margin-bottom: 32px; }

    .upload-box {
      border: 2px dashed #ccc; border-radius: 12px; padding: 48px;
      text-align: center; background: white; cursor: pointer;
      transition: border-color .2s;
    }
    .upload-box:hover, .upload-box.dragover { border-color: #4f46e5; }
    .upload-box input { display: none; }
    .upload-icon { font-size: 3rem; margin-bottom: 12px; }
    .upload-text { color: #666; }
    .upload-text strong { color: #4f46e5; }

    .btn {
      display: inline-block; padding: 12px 28px; background: #4f46e5; color: white;
      border: none; border-radius: 8px; font-size: 1rem; cursor: pointer;
      margin-top: 20px; transition: background .2s;
    }
    .btn:hover { background: #4338ca; }
    .btn:disabled { background: #9ca3af; cursor: not-allowed; }

    #status { margin: 20px 0; padding: 12px 16px; border-radius: 8px; display: none; font-size: .95rem; }
    #status.loading { background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; }
    #status.error   { background: #fef2f2; color: #dc2626; border: 1px solid #fecaca; }

    #result { display: none; margin-top: 32px; }

    .card { background: white; border-radius: 12px; padding: 24px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
    .card h2 { font-size: 1.1rem; font-weight: 600; margin-bottom: 16px; color: #111; border-bottom: 1px solid #eee; padding-bottom: 10px; }

    .meta-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
    .meta-item label { font-size: .75rem; text-transform: uppercase; color: #999; font-weight: 600; }
    .meta-item value { display: block; font-size: 1rem; font-weight: 500; margin-top: 2px; }

    .confidence-bar { height: 8px; background: #e5e7eb; border-radius: 4px; margin-top: 4px; }
    .confidence-fill { height: 100%; border-radius: 4px; background: #10b981; }
    .confidence-fill.medium { background: #f59e0b; }
    .confidence-fill.low { background: #ef4444; }

    .exp-entry { border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; margin-bottom: 12px; }
    .exp-header { display: flex; justify-content: space-between; align-items: flex-start; }
    .exp-title { font-weight: 600; font-size: 1rem; }
    .exp-company { color: #4f46e5; font-size: .9rem; margin-top: 2px; }
    .exp-dates { font-size: .85rem; color: #666; white-space: nowrap; }
    .exp-location { font-size: .85rem; color: #999; margin-top: 4px; }
    .bullets { margin-top: 10px; padding-left: 20px; }
    .bullets li { font-size: .9rem; margin-bottom: 4px; color: #444; }
    .badge { display: inline-block; padding: 3px 8px; border-radius: 4px; font-size: .75rem; background: #f3f4f6; color: #374151; margin-right: 4px; margin-bottom: 4px; }
    .badge.current { background: #dcfce7; color: #166534; }

    .skills-wrap { display: flex; flex-wrap: wrap; gap: 6px; }

    .route { font-family: monospace; font-size: .85rem; color: #4f46e5; }
    .warning { font-size: .85rem; color: #d97706; }

    .json-toggle { font-size: .85rem; color: #4f46e5; cursor: pointer; text-decoration: underline; margin-top: 8px; display: inline-block; }
    #raw-json { display: none; margin-top: 12px; background: #1e1e2e; color: #cdd6f4; padding: 16px; border-radius: 8px; font-size: .8rem; font-family: monospace; white-space: pre; overflow-x: auto; max-height: 500px; }
  </style>
</head>
<body>
<div class="container">
  <h1>Resume Parser</h1>
  <p class="sub">Upload a PDF resume to extract structured data using Gemini.</p>

  <div class="upload-box" id="drop-zone" onclick="document.getElementById('file-input').click()">
    <div class="upload-icon">📄</div>
    <p class="upload-text"><strong>Click to upload</strong> or drag & drop a PDF</p>
    <p class="upload-text" style="font-size:.85rem;margin-top:6px" id="file-name">No file selected</p>
    <input type="file" id="file-input" accept=".pdf" onchange="onFileSelected(this)">
  </div>
  <br>
  <button class="btn" id="parse-btn" onclick="parseResume()" disabled>Parse Resume</button>

  <div id="status"></div>
  <div id="result"></div>
</div>

<script>
let selectedFile = null;

function onFileSelected(input) {
  if (input.files[0]) {
    selectedFile = input.files[0];
    document.getElementById('file-name').textContent = selectedFile.name;
    document.getElementById('parse-btn').disabled = false;
  }
}

const zone = document.getElementById('drop-zone');
zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
zone.addEventListener('drop', e => {
  e.preventDefault();
  zone.classList.remove('dragover');
  const f = e.dataTransfer.files[0];
  if (f && f.name.endsWith('.pdf')) {
    selectedFile = f;
    document.getElementById('file-name').textContent = f.name;
    document.getElementById('file-input').files = e.dataTransfer.files;
    document.getElementById('parse-btn').disabled = false;
  }
});

async function parseResume() {
  if (!selectedFile) return;
  const btn = document.getElementById('parse-btn');
  const status = document.getElementById('status');
  const result = document.getElementById('result');

  btn.disabled = true;
  result.style.display = 'none';
  status.className = 'loading';
  status.style.display = 'block';
  status.textContent = '⏳ Parsing resume... (this may take 10–20s)';

  const fd = new FormData();
  fd.append('file', selectedFile);

  try {
    const resp = await fetch('/parse', { method: 'POST', body: fd });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'Parse failed');
    status.style.display = 'none';
    renderResult(data);
  } catch(e) {
    status.className = 'error';
    status.textContent = '❌ ' + e.message;
  } finally {
    btn.disabled = false;
  }
}

function confClass(v) {
  if (v >= 0.7) return '';
  if (v >= 0.4) return 'medium';
  return 'low';
}

function renderResult(d) {
  const result = document.getElementById('result');
  result.style.display = 'block';

  const conf = d.confidence?.overall ?? 0;
  const confPct = Math.round(conf * 100);

  const yoe = d.total_experience_years;
  const yoeDisplay = yoe != null ? `${yoe} yr${yoe !== 1 ? 's' : ''}` : '—';

  let html = `
  <div class="card">
    <h2>Document</h2>
    <div class="meta-grid">
      <div class="meta-item"><label>Source Type</label><value>${d.document.source_type}</value></div>
      <div class="meta-item"><label>Pages</label><value>${d.document.pages}</value></div>
      <div class="meta-item"><label>Language</label><value>${d.document.language || 'unknown'}</value></div>
      <div class="meta-item"><label>FTE Experience</label><value style="font-size:1.2rem;font-weight:700;color:#4f46e5">${yoeDisplay}</value></div>
      <div class="meta-item">
        <label>Confidence</label>
        <value>${confPct}%</value>
        <div class="confidence-bar"><div class="confidence-fill ${confClass(conf)}" style="width:${confPct}%"></div></div>
      </div>
    </div>
  </div>`;

  if (d.sections?.summary) {
    html += `<div class="card"><h2>Summary</h2><p style="font-size:.9rem;line-height:1.6">${d.sections.summary}</p></div>`;
  }

  if (d.experience?.length) {
    html += `<div class="card"><h2>Experience (${d.experience.length})</h2>`;
    for (const exp of d.experience) {
      const dates = [exp.start_date, exp.is_current ? 'Present' : exp.end_date].filter(Boolean).join(' – ');
      const etype = exp.employment_type || 'full_time';
      const etypeColors = { intern: '#fef9c3|#854d0e', part_time: '#f3f4f6|#6b7280', freelance: '#ede9fe|#5b21b6', contract: '#e0f2fe|#075985', full_time: '#dcfce7|#166534' };
      const [etypeBg, etypeText] = (etypeColors[etype] || etypeColors.full_time).split('|');
      const etypeLabel = etype.replace('_', '-');
      html += `
      <div class="exp-entry">
        <div class="exp-header">
          <div>
            <div class="exp-title">${exp.title || '—'} ${exp.is_current ? '<span class="badge current">Current</span>' : ''} <span class="badge" style="background:${etypeBg};color:${etypeText}">${etypeLabel}</span></div>
            <div class="exp-company">${exp.company || '—'}</div>
            ${exp.location ? `<div class="exp-location">📍 ${exp.location}</div>` : ''}
          </div>
          <div class="exp-dates">${dates}</div>
        </div>
        ${exp.bullets?.length ? `<ul class="bullets">${exp.bullets.map(b => `<li>${b}</li>`).join('')}</ul>` : ''}
      </div>`;
    }
    html += `</div>`;
  }

  if (d.sections?.skills?.length) {
    html += `<div class="card"><h2>Skills (${d.sections.skills.length})</h2><div class="skills-wrap">`;
    html += d.sections.skills.map(s => `<span class="badge">${s}</span>`).join('');
    html += `</div></div>`;
  }

  if (d.sections?.education?.length) {
    html += `<div class="card"><h2>Education</h2>`;
    for (const edu of d.sections.education) {
      html += `<div class="exp-entry">
        <div class="exp-title">${edu.degree || '—'}</div>
        <div class="exp-company">${edu.institution || '—'}</div>
        ${edu.gpa ? `<div class="exp-location">GPA: ${edu.gpa}</div>` : ''}
      </div>`;
    }
    html += `</div>`;
  }

  // Trace + cost
  const warnings = d.trace?.warnings || [];
  const route = d.trace?.route || [];
  const apiCalls = d.trace?.api_calls || [];
  const totalCost = d.trace?.total_cost_usd ?? 0;

  const costRows = apiCalls.map(c => {
    const note = c.note === 'exact' ? '' : ' <span style="color:#9ca3af;font-size:.75rem">(est)</span>';
    return `<tr>
      <td style="padding:4px 8px;font-size:.85rem">${c.step}${note}</td>
      <td style="padding:4px 8px;font-size:.85rem;text-align:right">${c.input_tokens.toLocaleString()}</td>
      <td style="padding:4px 8px;font-size:.85rem;text-align:right">${c.output_tokens.toLocaleString()}</td>
      <td style="padding:4px 8px;font-size:.85rem;text-align:right;font-weight:600">$${c.cost_usd.toFixed(6)}</td>
    </tr>`;
  }).join('');

  html += `<div class="card"><h2>Pipeline Trace</h2>
    <div class="route">${route.join(' → ')}</div>
    ${warnings.length ? `<div class="warning" style="margin-top:8px">⚠ ${warnings.join('; ')}</div>` : ''}
    ${apiCalls.length ? `
    <table style="width:100%;border-collapse:collapse;margin-top:12px">
      <thead><tr style="border-bottom:1px solid #e5e7eb">
        <th style="padding:4px 8px;font-size:.75rem;text-align:left;color:#999">Step</th>
        <th style="padding:4px 8px;font-size:.75rem;text-align:right;color:#999">In tokens</th>
        <th style="padding:4px 8px;font-size:.75rem;text-align:right;color:#999">Out tokens</th>
        <th style="padding:4px 8px;font-size:.75rem;text-align:right;color:#999">Cost</th>
      </tr></thead>
      <tbody>${costRows}</tbody>
      <tfoot><tr style="border-top:2px solid #e5e7eb">
        <td colspan="3" style="padding:4px 8px;font-size:.85rem;font-weight:600">Total</td>
        <td style="padding:4px 8px;font-size:.9rem;font-weight:700;color:#4f46e5;text-align:right">$${totalCost.toFixed(6)}</td>
      </tr></tfoot>
    </table>` : ''}
    <span class="json-toggle" onclick="toggleJson()">View raw JSON</span>
    <pre id="raw-json">${JSON.stringify(d, null, 2)}</pre>
  </div>`;

  result.innerHTML = html;
}

function toggleJson() {
  const el = document.getElementById('raw-json');
  el.style.display = el.style.display === 'none' ? 'block' : 'none';
}
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress access logs

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML.encode())

    def do_POST(self):
        if self.path != "/parse":
            self.send_response(404)
            self.end_headers()
            return

        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._json_error(400, "Expected multipart/form-data")
            return

        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type},
        )

        file_field = form["file"]
        if not file_field.filename:
            self._json_error(400, "No file uploaded")
            return

        data = file_field.file.read()

        # Write to temp file
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(data)
            tmp_path = f.name

        try:
            from app.core.hashing import sha256_hex
            from app.pipeline import orchestrator

            file_hash = sha256_hex(data)
            result = asyncio.run(orchestrator.run(
                job_id="ui-test",
                file_path=tmp_path,
                file_hash=file_hash,
                force_ocr=False,
            ))
            result_dict = result.model_dump(mode="json")
            body = json.dumps(result_dict).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self._json_error(500, str(e))
        finally:
            os.unlink(tmp_path)

    def _json_error(self, code, msg):
        body = json.dumps({"error": msg}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    # Need python-dotenv for loading .env
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass  # already loaded above or env vars set manually

    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"Resume Parser UI → http://localhost:{port}")
    print("Press Ctrl+C to stop.\n")
    server.serve_forever()
