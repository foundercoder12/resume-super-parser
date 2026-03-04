"""
Heuristic text quality scoring.

Score 0.0 (unreadable junk) → 1.0 (clean digital text).
Score below OCR_QUALITY_THRESHOLD triggers Mistral OCR.

Signals:
  - word_count:           too few words → likely image-only
  - garble_ratio:         high proportion of non-printable/non-ASCII chars
  - repetitive_char_ratio: lines with >80% same char → scan artifacts
  - line_length_cv:       coefficient of variation — good text has varied line lengths
"""
from __future__ import annotations
import re
import statistics

from app.schemas.internal import ExtractedDocument

_GARBLE_RE = re.compile(r"[^\x09\x0a\x0d\x20-\x7e\u00a0-\u024f]")


def score(doc: ExtractedDocument) -> float:
    text = doc.full_text
    if not text or len(text.strip()) < 30:
        return 0.0

    total_chars = len(text)
    garble_chars = len(_GARBLE_RE.findall(text))
    garble_ratio = garble_chars / total_chars

    words = text.split()
    word_count = len(words)

    lines = [ln for ln in text.splitlines() if ln.strip()]
    line_lengths = [len(ln) for ln in lines]

    # Coefficient of variation: good text has varied line lengths
    if len(line_lengths) > 1:
        mean_len = statistics.mean(line_lengths)
        stdev_len = statistics.stdev(line_lengths)
        cv = stdev_len / mean_len if mean_len > 0 else 0.0
    else:
        cv = 0.0

    def _is_repetitive(line: str) -> bool:
        if len(line) < 5:
            return False
        return max(line.count(c) for c in set(line)) / len(line) > 0.8

    repetitive_ratio = sum(1 for ln in lines if _is_repetitive(ln)) / max(len(lines), 1)

    word_score      = min(word_count / 100, 1.0)
    garble_score    = max(0.0, 1.0 - garble_ratio * 5)
    variety_score   = min(cv / 2.0, 1.0)   # cap at 2.0 to avoid over-penalising
    clean_ratio     = 1.0 - repetitive_ratio

    quality = (
        0.40 * word_score
        + 0.35 * garble_score
        + 0.15 * variety_score
        + 0.10 * clean_ratio
    )
    return round(min(max(quality, 0.0), 1.0), 4)


def classify_source_type(quality: float) -> str:
    if quality >= 0.7:
        return "digital"
    elif quality <= 0.3:
        return "scanned"
    return "hybrid"
