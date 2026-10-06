"""Extract a single JSON object from model text. Rejects prose and fences."""

from __future__ import annotations

import json
import re
from typing import Any


def extract_json_object(text: str) -> dict[str, Any]:
    """
    Parse one JSON object from raw model output.

    Accepts a bare object, or an object wrapped in ``` / ```json fences.
    Rejects empty output, non-objects, and text with no JSON object.
    """
    if text is None or not str(text).strip():
        raise ValueError("Empty model output; expected a JSON object")

    raw = str(text).strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, count=1, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```\s*$", "", raw)

    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Model output did not contain a JSON object")

    data = json.loads(raw[start : end + 1])
    if not isinstance(data, dict):
        raise TypeError(f"Expected a JSON object, got {type(data).__name__}")
    return data
