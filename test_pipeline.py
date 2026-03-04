"""
Quick end-to-end pipeline test — no web server or DB required.
Usage: PYTHONPATH=. python3 test_pipeline.py /path/to/resume.pdf
"""
import asyncio
import sys
import json
from pathlib import Path


async def main(pdf_path: str):
    from app.core.logging import configure_logging
    configure_logging()

    from app.pipeline import orchestrator
    from app.core.hashing import sha256_hex

    data = Path(pdf_path).read_bytes()
    file_hash = sha256_hex(data)

    print(f"\n=== Resume Parser Pipeline Test ===")
    print(f"File:  {pdf_path}")
    print(f"Size:  {len(data):,} bytes")
    print(f"Hash:  {file_hash[:16]}...\n")

    result = await orchestrator.run(
        job_id="test-job-001",
        file_path=pdf_path,
        file_hash=file_hash,
        force_ocr=False,
    )

    print(f"Source type:      {result.document.source_type}")
    print(f"Pages:            {result.document.pages}")
    print(f"Pipeline route:   {' → '.join(result.trace.route)}")
    print(f"Warnings:         {result.trace.warnings or 'none'}")
    print(f"Overall confidence: {result.confidence.overall}")
    print(f"\nExperience entries: {len(result.experience)}")
    for i, exp in enumerate(result.experience, 1):
        print(f"  [{i}] {exp.title or '?'} @ {exp.company or '?'} ({exp.start_date} – {exp.end_date or 'present'})")
        print(f"      Bullets: {len(exp.bullets)}  Confidence: {exp.confidence.overall:.2f}")

    print(f"\nSkills ({len(result.sections.skills)}): {', '.join(result.sections.skills[:10])}")
    print(f"Education: {len(result.sections.education)} entries")

    print("\n=== Full JSON Output ===")
    print(json.dumps(result.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: PYTHONPATH=. python3 test_pipeline.py /path/to/resume.pdf")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
