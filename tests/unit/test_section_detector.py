from app.pipeline.steps.section_detector import detect

SAMPLE_RESUME = """
John Doe
john@example.com

Summary
Experienced software engineer with 5 years in backend development.

Experience
Software Engineer
Acme Inc | Jan 2021 – Present | Bengaluru, India
- Built REST APIs using FastAPI
- Improved system performance by 30%

Data Analyst
Beta Corp | June 2018 – Dec 2020 | Mumbai, India
- Analyzed datasets using Python and SQL

Education
B.S. Computer Science
Stanford University | 2014 – 2018

Skills
Python, SQL, FastAPI, Docker
"""


def test_detects_known_sections():
    sections = detect(SAMPLE_RESUME)
    assert "experience" in sections
    assert "education" in sections
    assert "skills" in sections


def test_experience_section_contains_job_content():
    sections = detect(SAMPLE_RESUME)
    exp_text = sections["experience"].text
    assert "Acme Inc" in exp_text or "Software Engineer" in exp_text


def test_headingless_resume_fallback():
    headingless = """
    Jane Smith | jane@example.com

    Acme Inc
    Senior Engineer | Jan 2020 – Present
    - Led migration to microservices
    - Managed team of 6

    Beta Corp
    Engineer | Mar 2017 – Dec 2019
    - Built payment processing module
    """
    sections = detect(headingless)
    # Should detect experience via heuristic fallback
    assert "experience" in sections
