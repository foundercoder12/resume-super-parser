# Resume Super Parser

A production-grade async microservice that ingests resume PDFs and returns structured JSON — with high accuracy on **Experience** extraction.

---

## Architecture

```
PDF Upload → PDF Extraction (PyMuPDF / pdfplumber)
           → Quality Scoring → OCR if needed (Mistral)
           → Semantic Section Detection (regex + Gemini LLM)
           → Structured Extraction (LangExtract + Gemini 2.5 Flash)
           → Normalization + YoE Calculation
           → Confidence Scoring
           → CanonicalResume JSON
```

**Stack:** FastAPI · Celery + Redis · PostgreSQL · PyMuPDF · pdfplumber · Mistral OCR · Google Gemini 2.5 Flash · LangExtract · Docker Compose

---

## Features

- **Dual PDF extraction** — PyMuPDF (primary, char-level bboxes) + pdfplumber fallback for multi-column layouts
- **Conditional OCR** — Mistral OCR only for scanned/low-quality PDFs (quality score < 0.6)
- **Semantic section detection** — regex fast-path + single batched Gemini call for unrecognised headings; module-level cache avoids repeat API calls
- **LangExtract extraction** — verbatim, char-grounded structured extraction (no hallucination risk)
- **Total YoE** — calculates full-time experience years, excluding internships/part-time; merges overlapping intervals
- **Per-parse cost tracking** — exact token counts for Gemini calls; estimated for LangExtract
- **Deduplication** — SHA-256 hash check via Redis; duplicate uploads return existing `job_id`
- **Async job queue** — Celery workers with retry/backoff; Flower dashboard for monitoring

---

## Output Schema (CanonicalResume)

```json
{
  "schema_version": "1.0",
  "document": { "doc_id": "...", "pages": 2, "source_type": "digital", "file_hash": "..." },
  "sections": {
    "summary": "...",
    "skills": ["Python", "React", "..."],
    "education": [{ "institution": "...", "degree": "...", "field": "...", "gpa": "..." }],
    "projects": [...],
    "certifications": [...]
  },
  "experience": [
    {
      "company": "Acme Corp",
      "title": "Software Engineer",
      "start_date": "2022-06",
      "end_date": "2024-01",
      "is_current": false,
      "employment_type": "full_time",
      "bullets": ["Built X...", "Led Y..."],
      "confidence": { "overall": 0.95 }
    }
  ],
  "total_experience_years": 3.5,
  "confidence": { "overall": 0.91 },
  "trace": {
    "route": ["pymupdf", "quality_score", "section_detect", "langextract", "normalize", "confidence_score"],
    "api_calls": [
      { "step": "section_detect", "input_tokens": 312, "output_tokens": 48, "cost_usd": 0.0000379, "note": "exact" },
      { "step": "langextract",    "input_tokens": 950, "output_tokens": 200, "cost_usd": 0.000131, "note": "estimated" }
    ],
    "total_cost_usd": 0.000169,
    "warnings": [],
    "errors": []
  }
}
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/resumes:parse` | Upload PDF, returns `job_id` |
| `GET`  | `/v1/jobs/{job_id}` | Poll job status |
| `GET`  | `/v1/jobs/{job_id}/result` | Fetch `CanonicalResume` when done |

### Upload a resume
```bash
curl -X POST http://localhost:8000/v1/resumes:parse \
  -F "file=@resume.pdf"
# → {"job_id": "abc123", "status": "pending", "poll_url": "/v1/jobs/abc123"}
```

### Poll status
```bash
curl http://localhost:8000/v1/jobs/abc123
# → {"status": "succeeded", ...}
```

### Fetch result
```bash
curl http://localhost:8000/v1/jobs/abc123/result
```

---

## Quick Start (Docker Compose)

**Prerequisites:** Docker, Docker Compose, API keys (see below)

```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env with your API keys

# 2. Start all services
make up

# 3. Run DB migrations
make migrate

# 4. Parse a resume
curl -X POST http://localhost:8000/v1/resumes:parse -F "file=@your_resume.pdf"
```

Services:
- **API** → `http://localhost:8000`
- **Frontend (dev UI)** → `http://localhost:8080` (run `python frontend_server.py`)
- **Flower (worker monitor)** → `http://localhost:5555`
- **API Docs** → `http://localhost:8000/docs`

---

## Local Development (without Docker)

```bash
# Python 3.11+ required
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Start Redis and Postgres (or use docker-compose for just those)
docker-compose up redis postgres -d

# Run migrations
make migrate-local

# Start API
uvicorn app.main:app --reload --port 8000

# Start worker (separate terminal)
make worker

# Start frontend
python frontend_server.py
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in:

| Variable | Description |
|----------|-------------|
| `GEMINI_API_KEY` | Google Gemini API key (section detection + extraction) |
| `MISTRAL_API_KEY` | Mistral API key (OCR for scanned PDFs) |
| `LANGEXTRACT_API_KEY` | LangExtract API key |
| `DATABASE_URL` | PostgreSQL async URL (`postgresql+asyncpg://...`) |
| `REDIS_URL` | Redis URL (`redis://localhost:6379/0`) |
| `OCR_QUALITY_THRESHOLD` | Quality score below which OCR is triggered (default: `0.6`) |

---

## Running Tests

```bash
# Unit tests
make test

# Integration tests (requires running services)
make test-integration
```

---

## Project Structure

```
app/
├── api/v1/          # FastAPI route handlers
├── core/            # Hashing, logging, cost calculation, exceptions
├── db/              # SQLAlchemy models, async session
├── pipeline/
│   ├── orchestrator.py
│   └── steps/       # pdf_extractor, quality_scorer, ocr_client,
│                    # section_detector, langextract_extractor,
│                    # normalizer, confidence_scorer
├── schemas/         # Pydantic models (canonical, api, internal)
├── storage/         # File store abstraction (local → S3-ready)
└── workers/         # Celery app + tasks
```

---

## Cost

Typical cost per resume parse: **~$0.0002 – $0.001** (Gemini 2.5 Flash non-thinking tier).
Exact cost is returned in `trace.total_cost_usd` on every parse result.
