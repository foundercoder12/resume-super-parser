from app.pipeline.steps.quality_scorer import score, classify_source_type
from app.schemas.internal import ExtractedDocument, PageText


def _make_doc(text: str) -> ExtractedDocument:
    return ExtractedDocument(
        full_text=text,
        pages=[PageText(page_number=0, text=text, char_offset=0, bboxes=[])],
        page_count=1,
        extraction_method="pymupdf",
    )


def test_empty_text_scores_zero():
    doc = _make_doc("")
    assert score(doc) == 0.0


def test_short_text_scores_zero():
    doc = _make_doc("hello")
    assert score(doc) == 0.0


def test_clean_resume_text_scores_high():
    text = """
    John Doe | john@example.com | New York, NY

    EXPERIENCE
    Software Engineer — Acme Inc, Jan 2021 – Present
    - Built scalable REST APIs using FastAPI and PostgreSQL
    - Reduced latency by 40% via query optimisation and caching
    - Led a team of 4 engineers across 3 product squads

    EDUCATION
    B.S. Computer Science — Stanford University, 2020

    SKILLS
    Python, FastAPI, PostgreSQL, Redis, Docker, Kubernetes
    """ * 3
    doc = _make_doc(text)
    s = score(doc)
    assert s >= 0.6, f"Expected >= 0.6, got {s}"


def test_garbled_text_scores_low():
    # C1 control chars (\x80-\x83) are outside allowed ranges, not whitespace,
    # so they are counted as garble → garble_score = 0 → overall score low
    garbled = "\x80\x81\x82\x83" * 250
    doc = _make_doc(garbled)
    assert score(doc) < 0.3


def test_classify_source_type():
    assert classify_source_type(0.9) == "digital"
    assert classify_source_type(0.5) == "hybrid"
    assert classify_source_type(0.1) == "scanned"
