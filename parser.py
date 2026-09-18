"""
GridWise – Operator Notes Parser (OpenRouter)
Converts unstructured operator notes into structured constraints
for the LP optimizer.  Includes a robust no-op fallback on failure.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Structured output schema
# ---------------------------------------------------------------------------

class ParsedConstraints(BaseModel):
    """Structured constraints extracted from operator notes."""
    no_charge_windows: list[list[int]] = Field(
        default_factory=list,
        description="List of [start, end] hour pairs where charging is forbidden.",
    )
    no_discharge_windows: list[list[int]] = Field(
        default_factory=list,
        description="List of [start, end] hour pairs where discharging is forbidden.",
    )
    max_grid_windows: list[dict[str, Any]] = Field(
        default_factory=list,
        description='List of {"start": int, "end": int, "max_kwh": float} windows limiting grid import.',
    )
    minimum_battery_reserve: float = Field(
        default=0.0,
        ge=0.0, le=1.0,
        description="Minimum battery state-of-charge as a fraction (0-1).",
    )


# ---------------------------------------------------------------------------
# No-op / safe defaults
# ---------------------------------------------------------------------------

NO_OP_CONSTRAINTS = ParsedConstraints()
EMPTY_NOTES_RESPONSE = json.dumps({
    "no_charge_windows": [],
    "no_discharge_windows": [],
    "max_grid_windows": [],
    "minimum_battery_reserve": 0.0,
})

# ---------------------------------------------------------------------------
# System prompt that tells the LLM how to respond
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an energy-system constraint parser. Given free-text operator notes
for a campus microgrid battery system, extract structured constraints.

Return ONLY a valid JSON object with exactly these keys (omit keys you
have no data for, but always include the full structure):

{
  "no_charge_windows": [[start_hour, end_hour], ...],
  "no_discharge_windows": [[start_hour, end_hour], ...],
  "max_grid_windows": [{"start": start_hour, "end": end_hour, "max_kwh": value}, ...],
  "minimum_battery_reserve": float  // 0.0 – 1.0
}

Rules:
- Hours are 0-indexed integers 0-23 inclusive.
- Use integer hour boundaries (e.g., "12 to 14" → [12, 14]).
- Percentages must be converted to 0-1 fractions (e.g., 20% → 0.2).
- If operator notes mention kWh limits on grid import, map them to max_grid_windows.
- If the notes are empty, contradictory, or unintelligible, return the empty
  schema with all values at their defaults.
- Return ONLY the JSON, no explanation or markdown fences.
"""


# ---------------------------------------------------------------------------
# Core parsing function
# ---------------------------------------------------------------------------

def parse_operator_notes(
    notes: str | None,
    *,
    api_key: str | None = None,
    base_url: str = "https://openrouter.ai/api/v1",
    model: str = "openai/gpt-4o-mini",
    timeout: int = 30,
) -> ParsedConstraints:
    """
    Call OpenRouter to parse free-text operator notes into structured
    constraints.  Falls back to NO_OP on any error or malformed output.

    Parameters
    ----------
    notes : str or None
        Raw operator notes text.
    api_key : str or None
        OpenRouter API key.  Falls back to ``OPENROUTER_API_KEY`` env var.
    base_url : str
        OpenRouter base URL.
    model : str
        Model identifier for the completion.
    timeout : int
        HTTP request timeout in seconds.
    """
    # --- Guard: empty / None notes → no-op immediately ---
    if not notes or not notes.strip():
        logger.info("Operator notes empty – returning no-op constraints.")
        return NO_OP_CONSTRAINTS

    api_key = api_key or os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        logger.warning(
            "No OPENROUTER_API_KEY configured – falling back to no-op constraints."
        )
        return NO_OP_CONSTRAINTS

    try:
        import requests as _requests  # local import so module loads without it
        from openai import OpenAI

        client = OpenAI(
            base_url=base_url,
            api_key=api_key,
        )

        response = client.chat.completions.create(
            model=model,
            timeout=timeout,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": notes},
            ],
            temperature=0.0,
        )

        raw = response.choices[0].message.content.strip()
        # Strip markdown fences if the model wraps JSON in ```json ... ```
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            if raw.endswith("```"):
                raw = raw[: -"```".__len__()]

        parsed_dict = json.loads(raw)
        constraints = ParsedConstraints(**parsed_dict)
        logger.info("Successfully parsed operator notes: %s", constraints)
        return constraints

    except Exception:
        logger.exception("Failed to parse operator notes via OpenRouter – returning no-op.")
        return NO_OP_CONSTRAINTS


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sample = (
        "No charging from hour 12 to 14. "
        "Keep at least 20% battery reserve at all times. "
        "Cap grid import at 50 kWh during hours 17-19."
    )
    result = parse_operator_notes(sample)
    print(json.dumps(result.model_dump(), indent=2))
