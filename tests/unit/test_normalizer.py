import pytest
from app.pipeline.steps.normalizer import normalize_date
from app.schemas.canonical import (
    CanonicalResume, ExperienceEntry, ExperienceConfidence,
    Sections, ConfidenceSet, PipelineTrace, DocumentMeta, Grounding,
)


def _make_resume(experience: list[ExperienceEntry]) -> CanonicalResume:
    return CanonicalResume(
        document=DocumentMeta(doc_id="test", pages=1, source_type="digital", file_hash="abc"),
        sections=Sections(),
        experience=experience,
        confidence=ConfidenceSet(overall=0.5),
        trace=PipelineTrace(),
    )


# ── Date normalization ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("January 2021",      "2021-01"),
    ("Jan 2021",          "2021-01"),
    ("2021-06",           "2021-06"),
    ("2019",              "2019"),
    ("June 2020",         "2020-06"),
    ("09/2022",           "2022-09"),
    (None,                None),
    ("present",           None),    # current → caller sets is_current
    ("Present",           None),
    ("",                  None),
])
def test_normalize_date(raw, expected):
    assert normalize_date(raw) == expected


# ── Entry normalization ────────────────────────────────────────────────────────

def test_present_end_date_sets_is_current():
    from app.pipeline.steps.normalizer import normalize
    entry = ExperienceEntry(
        company="Acme",
        title="Engineer",
        start_date="January 2021",
        end_date="Present",
        is_current=False,
        bullets=["Did something"],
        confidence=ExperienceConfidence(),
        grounding=Grounding(),
    )
    result = normalize(_make_resume([entry]))
    assert result.experience[0].is_current is True
    assert result.experience[0].end_date is None
    assert result.experience[0].start_date == "2021-01"


def test_lowercase_bullet_merge():
    from app.pipeline.steps.normalizer import normalize
    entry = ExperienceEntry(
        company="Acme",
        title="Engineer",
        start_date="2021",
        end_date="2023",
        is_current=False,
        bullets=["Built a service", "that handles high traffic"],
        confidence=ExperienceConfidence(),
        grounding=Grounding(),
    )
    result = normalize(_make_resume([entry]))
    assert result.experience[0].bullets == ["Built a service that handles high traffic"]


def test_skill_deduplication():
    from app.pipeline.steps.normalizer import normalize
    from app.schemas.canonical import Sections
    resume = _make_resume([])
    resume = resume.model_copy(update={
        "sections": Sections(skills=["Python", "python", "PYTHON", "FastAPI"])
    })
    result = normalize(resume)
    assert len(result.sections.skills) == 2
