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
    load_report_schema(path=None) -> dict
    call_llm(system_prompt, user_content, images=None, model=None, max_tokens=4000, force_json=True) -> str
    validate_findings(raw_json_str, schema=None) -> list[dict]
    validate_report(raw_json_str_or_dict, schema=None) -> Optional[dict]
    assign_uuid_if_missing(findings) -> list[dict]
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Optional, Union

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
DEFAULT_REPORT_SCHEMA_PATH = Path(
    os.environ.get("A11Y_REPORT_SCHEMA_PATH", _REPO_ROOT / "schemas" / "report.schema.json")
)

# Default model: a free-tier-eligible Gemini model. Override with GEMINI_MODEL env
# var if needed.
# Note: gemini-3.5-flash's free tier is only ~5 requests/minute — too tight for
# a pipeline making many small structured-extraction calls. gemini-3.1-flash-lite
# gets 15-30 RPM on the free tier and is actually the better fit for this kind of
# task (classification/extraction, not deep reasoning), not just the cheaper one.
# Google periodically retires older model IDs for new accounts (e.g.
# gemini-2.5-flash was retired for new users in 2026) — if you get a 404
# NOT_FOUND error mentioning a model name, check the current free-tier lineup
# at https://ai.google.dev/gemini-api/docs/models and update this default or
# your GEMINI_MODEL env var accordingly.
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")

# Retry/backoff config for 429 (rate limit) errors. Free-tier RPM limits are low
# enough that a batch of calls in a tight loop will routinely hit them; retrying
# with backoff is expected/normal here, not an edge case.
MAX_RETRIES = int(os.environ.get("A11Y_LLM_MAX_RETRIES", "5"))
INITIAL_BACKOFF_SECONDS = float(os.environ.get("A11Y_LLM_INITIAL_BACKOFF", "2.0"))
BACKOFF_MULTIPLIER = 2.0

_wcag_cache: Optional[dict] = None
_schema_cache: Optional[dict] = None
_report_schema_cache: Optional[dict] = None


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


def load_report_schema(path: Optional[Path] = None) -> dict:
    """Load report.schema.json once and cache it."""
    global _report_schema_cache
    if _report_schema_cache is not None and path is None:
        return _report_schema_cache
    p = Path(path) if path else DEFAULT_REPORT_SCHEMA_PATH
    with open(p, "r", encoding="utf-8") as f:
        schema = json.load(f)
    if path is None:
        _report_schema_cache = schema
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


def _is_rate_limit_error(exc: Exception) -> bool:
    """Detect a 429 from the google-genai SDK. The SDK surfaces this as a
    ClientError/APIError with a .code attribute in some versions and only in
    the string message in others, so check both rather than relying on one."""
    code = getattr(exc, "code", None)
    if code == 429:
        return True
    return "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc)


def call_llm(
    system_prompt: str,
    user_content: str,
    images: Optional[list] = None,
    model: Optional[str] = None,
    max_tokens: int = 4000,
    force_json: bool = True,
) -> str:
    """
    Wraps the Gemini API (google-genai SDK) generate_content call.

    images: optional list of file paths (or raw PNG bytes) to attach as image
    parts alongside the text content.

    force_json: when True (default), sets response_mime_type="application/json"
    so Gemini is constrained to emit strict JSON instead of relying on prompt
    instructions alone. This fixes two problems seen in practice: (1) the model
    padding its output with conversational prose/markdown fences that pushed
    genuine content past max_output_tokens and got cut off mid-string ("Unterminated
    string" JSON parse errors), and (2) needing to strip markdown fences at all.
    Set to False only for calls that intentionally want free-form text back.

    max_tokens default raised from 2000 to 4000 — the truncation errors were
    partly just running out of budget on larger batch responses (e.g. synthesis's
    per-group calls, priority ordering over the full issue list), not only the
    prose-padding issue force_json addresses.

    Retries with exponential backoff on 429 (rate limit) errors, since free-tier
    RPM limits are low enough that hitting one mid-run is normal, not exceptional.
    Still raises on non-429 API errors, and on 429s that persist past MAX_RETRIES,
    so callers can decide how to handle a real failure (agents should catch and
    log, not let one bad call crash a whole batch).

    Returns response.text.

    Auth: reads GEMINI_API_KEY (or GOOGLE_API_KEY) from the environment
    automatically via genai.Client() — get a free key at
    https://aistudio.google.com (Get API key -> Create API key).
    """
    import time

    from google import genai  # imported lazily so this module has no hard dependency at import time
    from google.genai import types

    client = genai.Client()

    parts: list = []
    if images:
        for img in images:
            parts.append(_build_image_part(img, types))
    parts.append(user_content)

    config_kwargs = dict(
        system_instruction=system_prompt,
        max_output_tokens=max_tokens,
    )
    if force_json:
        config_kwargs["response_mime_type"] = "application/json"

    backoff = INITIAL_BACKOFF_SECONDS
    last_exc: Optional[Exception] = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=model or DEFAULT_MODEL,
                contents=parts,
                config=types.GenerateContentConfig(**config_kwargs),
            )
            return response.text or ""
        except Exception as e:  # noqa: BLE001 - SDK exception types vary by version
            if not _is_rate_limit_error(e) or attempt == MAX_RETRIES:
                raise
            last_exc = e
            logger.warning(
                "call_llm: rate limited (attempt %d/%d), backing off %.1fs before retry: %s",
                attempt, MAX_RETRIES, backoff, e,
            )
            time.sleep(backoff)
            backoff *= BACKOFF_MULTIPLIER

    # Unreachable in practice (loop either returns or raises), but keeps type
    # checkers happy and fails loudly if it's ever hit.
    raise last_exc or RuntimeError("call_llm: exhausted retries with no exception captured")


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
        error_msg = f"validate_findings: could not parse JSON from model output: {e}\nRaw output:\n{raw_json_str}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

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


def validate_report(raw_json_str_or_dict: Union[str, dict], schema: Optional[dict] = None) -> Optional[dict]:
    """
    Validate a full report object (not a list) against report.schema.json.

    Accepts either a raw JSON string (markdown fences tolerated) or an
    already-parsed dict. Returns the parsed/validated dict on success, or
    None (logged) if parsing or schema validation fails — synthesis_agent
    should treat a None return as "do not write this report.json", not
    silently proceed.
    """
    import jsonschema

    schema = schema or load_report_schema()

    if isinstance(raw_json_str_or_dict, dict):
        data = raw_json_str_or_dict
    else:
        cleaned = _strip_markdown_fences(raw_json_str_or_dict)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error("validate_report: could not parse JSON: %s", e)
            return None

    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.exceptions.ValidationError as e:
        logger.error("validate_report: report failed schema validation: %s", e.message)
        return None

    return data