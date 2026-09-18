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
        ge=0.0,
        description="Minimum battery reserve. Values <=1.0 are treated as a fraction of capacity; values >1.0 are treated as absolute kWh.",
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
  "minimum_battery_reserve": float  // fraction 0.0 – 1.0 OR absolute kWh value
}

Rules:
- Hours are 0-indexed integers 0-23 inclusive.
- Use integer hour boundaries (e.g., "12 to 14" → [12, 14]).
- Percentages must be converted to 0-1 fractions (e.g., 20% → 0.2).
- If operator notes mention kWh limits on grid import, map them to max_grid_windows.
- If notes mention a minimum battery reserve in kWh (e.g., "25 kWh"), set
  minimum_battery_reserve to the kWh value as-is (the optimizer will handle it).
- If notes mention a minimum battery reserve as a percentage (e.g., "20%"),
  set minimum_battery_reserve to the fraction (e.g., 0.2).
- If the notes are empty, contradictory, or unintelligible, return the empty
  schema with all values at their defaults.
- Return ONLY the JSON, no explanation or markdown fences.
"""


# ---------------------------------------------------------------------------
# Rule-based fallback parser (works without API key)
# ---------------------------------------------------------------------------

import re


def _rule_based_parse(notes: str) -> ParsedConstraints:
    """
    Simple regex-based parser for common operator note patterns.
    Returns ParsedConstraints with any matches found.
    """
    result = ParsedConstraints()
    lower = notes.lower()

    # Pattern: "no charging during hour X" / "no charging from X to Y"
    for m in re.finditer(r'no\s+charg\w+.*?(?:hour|from|at)\s+(\d+)(?:\s*to\s*(\d+))?', lower):
        h1 = int(m.group(1))
        h2 = int(m.group(2)) + 1 if m.group(2) else h1 + 1
        result.no_charge_windows.append([h1, h2])

    # Pattern: "no discharging during hour X" / "no discharge from X to Y"
    for m in re.finditer(r'no\s+discharg\w+.*?(?:hour|from|at)\s+(\d+)(?:\s*to\s*(\d+))?', lower):
        h1 = int(m.group(1))
        h2 = int(m.group(2)) + 1 if m.group(2) else h1 + 1
        result.no_discharge_windows.append([h1, h2])

    # Pattern: "cap grid at X kWh" / "grid cap X kWh" at hour(s)
    for m in re.finditer(r'(?:cap|limit).*?grid.*?(\d+)\s*kwh.*?(?:hour|at|from)\s*(\d+)(?:\s*to\s*(\d+))?', lower):
        max_kw = float(m.group(1))
        h1 = int(m.group(2))
        h2 = int(m.group(3)) + 1 if m.group(3) else h1 + 1
        result.max_grid_windows.append({"start": h1, "end": h2, "max_kwh": max_kw})
    for m in re.finditer(r'(?:cap|limit).*?grid.*?(?:hour|at|from)\s*(\d+)(?:\s*to\s*(\d+))?.*?(\d+)\s*kwh', lower):
        h1 = int(m.group(1))
        h2 = int(m.group(2)) + 1 if m.group(2) else h1 + 1
        max_kw = float(m.group(3))
        result.max_grid_windows.append({"start": h1, "end": h2, "max_kwh": max_kw})

    # Pattern: "minimum battery reserve X kWh" or "keep X kWh reserve"
    m = re.search(r'(?:minimum|keep|min).*?(?:battery|reserve).*?(\d+(?:\.\d+)?)\s*kwh', lower)
    if m:
        result.minimum_battery_reserve = float(m.group(1))  # absolute kWh

    # Pattern: "minimum battery reserve X%"
    m = re.search(r'(?:minimum|keep|min).*?(?:battery|reserve).*?(\d+(?:\.\d+)?)\s*%', lower)
    if m:
        result.minimum_battery_reserve = float(m.group(1)) / 100.0  # fraction

    return result


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
    # --- Guard: empty / None notes → try rule-based fallback first, then no-op ---
    if not notes or not notes.strip():
        logger.info("Operator notes empty – returning no-op constraints.")
        return NO_OP_CONSTRAINTS

    # Try rule-based parsing first (works without API key)
    rule_result = _rule_based_parse(notes)
    if any([rule_result.no_charge_windows,
            rule_result.no_discharge_windows,
            rule_result.max_grid_windows,
            rule_result.minimum_battery_reserve > 0]):
        logger.info("Rule-based parse succeeded: %s", rule_result)
        return rule_result

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
