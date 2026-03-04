"""
API cost helpers for Gemini 2.5 Flash.

Pricing (as of 2025-03):
  Input:  $0.075 / 1M tokens
  Output: $0.30  / 1M tokens
  (non-thinking mode, prompts ≤ 200K tokens)

Token estimation for LangExtract: the library doesn't expose usage metadata,
so we estimate from character count (1 token ≈ 4 chars for English text).
"""
from __future__ import annotations

# Gemini 2.5 Flash non-thinking pricing
_INPUT_COST_PER_TOKEN  = 0.075 / 1_000_000
_OUTPUT_COST_PER_TOKEN = 0.30  / 1_000_000

# LangExtract fixed overhead: prompt_description + few-shot examples
# (measured by counting chars in the EXAMPLES + PROMPT_DESCRIPTION strings)
_LANGEXTRACT_FIXED_INPUT_CHARS = 3_800   # ~950 tokens


def gemini_cost(input_tokens: int, output_tokens: int) -> float:
    return round(
        input_tokens * _INPUT_COST_PER_TOKEN
        + output_tokens * _OUTPUT_COST_PER_TOKEN,
        8,
    )


def estimate_from_chars(input_chars: int, output_chars: int) -> tuple[int, int, float]:
    """
    Estimate (input_tokens, output_tokens, cost_usd) from character counts.
    Uses 4 chars/token heuristic plus LangExtract fixed overhead.
    """
    input_tokens  = (input_chars + _LANGEXTRACT_FIXED_INPUT_CHARS) // 4
    output_tokens = output_chars // 4
    return input_tokens, output_tokens, gemini_cost(input_tokens, output_tokens)
