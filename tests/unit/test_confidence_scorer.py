from app.pipeline.steps.confidence_scorer import score
from app.schemas.canonical import (
    CanonicalResume, ExperienceEntry, ExperienceConfidence,
    Sections, ConfidenceSet, PipelineTrace, DocumentMeta, Grounding,
)


def _make_resume(entries: list[ExperienceEntry]) -> CanonicalResume:
    return CanonicalResume(
        document=DocumentMeta(doc_id="test", pages=1, source_type="digital", file_hash="abc"),
        sections=Sections(
            skills=["Python", "FastAPI"],
            education=[],
        ),
        experience=entries,
        confidence=ConfidenceSet(overall=0.0),
        trace=PipelineTrace(),
    )


def _entry(**kwargs) -> ExperienceEntry:
    defaults = dict(
        company="Acme Inc",
        title="Engineer",
        start_date="2021-01",
        end_date="2023-06",
        is_current=False,
        bullets=["Built REST APIs", "Improved latency by 30%"],
        confidence=ExperienceConfidence(),
        grounding=Grounding(),
    )
    defaults.update(kwargs)
    return ExperienceEntry(**defaults)


def test_well_formed_entry_scores_high():
    resume = score(_make_resume([_entry()]))
    conf = resume.experience[0].confidence
    assert conf.overall >= 0.7
    assert conf.company == 1.0
    assert conf.title == 1.0


def test_missing_company_reduces_score():
    resume = score(_make_resume([_entry(company=None)]))
    conf = resume.experience[0].confidence
    assert conf.company == 0.0
    assert conf.overall < 0.8


def test_empty_bullets_reduces_score():
    resume = score(_make_resume([_entry(bullets=[])]))
    conf = resume.experience[0].confidence
    assert conf.bullets == 0.3


def test_overall_confidence_non_zero_with_experience():
    resume = score(_make_resume([_entry()]))
    assert resume.confidence.overall > 0.0
    assert resume.confidence.experience is not None
