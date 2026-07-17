"""
base_agent.py — shared, dependency-light utilities used by every inspection agent
(screen_reader_agent.py, visual_agent.py, and later motor_agent.py / synthesis logic
from Person 3). Keep this file free of screen-reader/visual-specific logic so it stays
a stable import for everyone.

Uses Google's Gemini API (free tier via Google AI Studio) rather than a paid LLM
provider, so this can run without any billing set up. See README.md for how to get
a free GEMINI_API_KEY.

Public API:
    load_wcag_criteria(path=None) -> dict[str, dict]
    load_finding_schema(path=None) -> dict
    call_llm(system_prompt, user_content, images=None, model=None, max_tokens=2000) -> str
    validate_findings(raw_json_str, schema=None) -> list[dict]
    assign_uuid_if_missing(findings) -> list[dict]
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger("a11yagents.base_agent")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Paths (repo-relative, overridable via env vars so this works regardless of
# where the script is invoked from)
# ---------------------------------------------------------------------------

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent

DEFAULT_WCAG_PATH = Path(os.environ.get("A11Y_WCAG_PATH", _REPO_ROOT / "wcag" / "wcag22_criteria.json"))
DEFAULT_FINDING_SCHEMA_PATH = Path(
    os.environ.get("A11Y_FINDING_SCHEMA_PATH", _REPO_ROOT / "schemas" / "finding.schema.json")
)

# Default model: a free-tier-eligible Gemini model. Override with GEMINI_MODEL env
# var if needed (e.g. "gemini-3.1-flash-lite" for higher rate limits on lighter tasks).
# Note: Google periodically retires older model IDs for new accounts (e.g.
# gemini-2.5-flash was retired for new users in 2026) — if you get a 404
# NOT_FOUND error mentioning a model name, check the current free-tier lineup
# at https://ai.google.dev/gemini-api/docs/models and update this default or
# your GEMINI_MODEL env var accordingly.
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")

_wcag_cache: Optional[dict] = None
_schema_cache: Optional[dict] = None


def load_wcag_criteria(path: Optional[Path] = None) -> dict:
    """Load wcag22_criteria.json once and cache it. Returns {criterion_id: {id, title, short_description}}."""
    global _wcag_cache
    if _wcag_cache is not None and path is None:
        return _wcag_cache
    p = Path(path) if path else DEFAULT_WCAG_PATH
    with open(p, "r", encoding="utf-8") as f:
        raw = json.load(f)
    by_id = {item["id"]: item for item in raw}
    if path is None:
        _wcag_cache = by_id
    return by_id


def load_finding_schema(path: Optional[Path] = None) -> dict:
    """Load finding.schema.json once and cache it."""
    global _schema_cache
    if _schema_cache is not None and path is None:
        return _schema_cache
    p = Path(path) if path else DEFAULT_FINDING_SCHEMA_PATH
    with open(p, "r", encoding="utf-8") as f:
        schema = json.load(f)
    if path is None:
        _schema_cache = schema
    return schema


# ---------------------------------------------------------------------------
# Gemini API wrapper (Google AI Studio free tier)
# ---------------------------------------------------------------------------

def _build_image_part(image_path_or_bytes, genai_types):
    """Build a google.genai.types.Part from a file path or raw bytes.
    Assumes PNG; adjust mime_type if you pass JPEGs."""
    if isinstance(image_path_or_bytes, (bytes, bytearray)):
        data = bytes(image_path_or_bytes)
    else:
        with open(image_path_or_bytes, "rb") as f:
            data = f.read()
    return genai_types.Part.from_bytes(data=data, mime_type="image/png")


def call_llm(
    system_prompt: str,
    user_content: str,
    images: Optional[list] = None,
    model: Optional[str] = None,
    max_tokens: int = 2000,
) -> str:
    """
    Wraps the Gemini API (google-genai SDK) generate_content call.

    images: optional list of file paths (or raw PNG bytes) to attach as image
    parts alongside the text content.

    Returns response.text. Raises on API errors so callers can decide how to
    handle failures (agents should catch and log, not let one bad call crash
    a whole batch).

    Auth: reads GEMINI_API_KEY (or GOOGLE_API_KEY) from the environment
    automatically via genai.Client() — get a free key at
    https://aistudio.google.com (Get API key -> Create API key).
    """
    from google import genai  # imported lazily so this module has no hard dependency at import time
    from google.genai import types

    client = genai.Client()

    parts: list = []
    if images:
        for img in images:
            parts.append(_build_image_part(img, types))
    parts.append(user_content)

    response = client.models.generate_content(
        model=model or DEFAULT_MODEL,
        contents=parts,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=max_tokens,
        ),
    )

    return response.text or ""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _strip_markdown_fences(raw: str) -> str:
    s = raw.strip()
    if s.startswith("```"):
        # drop first fence line (``` or ```json) and trailing fence
        lines = s.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        s = "\n".join(lines)
    return s.strip()


def validate_findings(raw_json_str: str, schema: Optional[dict] = None) -> list[dict]:
    """
    Strip markdown fences if present, json.loads, validate each item against
    finding.schema.json via jsonschema, drop and log invalid entries rather
    than crashing.
    """
    import jsonschema

    schema = schema or load_finding_schema()
    cleaned = _strip_markdown_fences(raw_json_str)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error("validate_findings: could not parse JSON from model output: %s", e)
        return []

    if isinstance(data, dict):
        # tolerate a top-level {"findings": [...]} wrapper
        data = data.get("findings", [])
    if not isinstance(data, list):
        logger.error("validate_findings: expected a list of findings, got %s", type(data))
        return []

    valid: list[dict] = []
    for i, item in enumerate(data):
        try:
            jsonschema.validate(instance=item, schema=schema)
            valid.append(item)
        except jsonschema.exceptions.ValidationError as e:
            logger.warning("validate_findings: dropping invalid finding at index %d: %s", i, e.message)

    return assign_uuid_if_missing(valid)


def assign_uuid_if_missing(findings: list[dict]) -> list[dict]:
    """Ensure every finding has a finding_id; assign a fresh uuid4 if absent/empty."""
    for f in findings:
        if not f.get("finding_id"):
            f["finding_id"] = str(uuid.uuid4())
    return findings