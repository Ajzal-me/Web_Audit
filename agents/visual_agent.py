"""
visual_agent.py — Person 2's second inspection agent.

Input: css_findings list (contrast_ratio, is_large_text, focus_indicator_visible —
already numerically computed by Person 1's extraction pipeline; we do NOT recompute
or estimate these in the LLM call) + a 200%-zoom full-page screenshot path for
qualitative reflow/overlap checking.

WCAG threshold logic (SC 1.4.3): 4.5:1 for normal text, 3:1 for large text. This is
applied in plain Python code BEFORE calling the LLM, so the LLM's job is producing
the finding record (issue_type, severity judgment, evidence, confidence) — not doing
arithmetic.

Output: a validated list of findings with "agent": "visual".
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from base_agent import call_llm, validate_findings, load_wcag_criteria

logger = logging.getLogger("a11yagents.visual_agent")

CANDIDATE_BATCH_SIZE = 10

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent

NORMAL_TEXT_THRESHOLD = 4.5
LARGE_TEXT_THRESHOLD = 3.0


def _wcag_list_str() -> str:
    criteria = load_wcag_criteria()
    lines = [f"- {cid}: {c['title']} — {c['short_description']}" for cid, c in criteria.items()]
    return "\n".join(lines)


def _compute_contrast_candidates(css_findings: list[dict]) -> list[dict]:
    """Pure-code threshold check per SC 1.4.3. Returns candidate dicts (not yet
    finding-schema-shaped) for anything failing the applicable threshold."""
    candidates = []
    for cf in css_findings:
        ratio = cf.get("contrast_ratio")
        if ratio is None:
            continue
        is_large = bool(cf.get("is_large_text", False))
        threshold = LARGE_TEXT_THRESHOLD if is_large else NORMAL_TEXT_THRESHOLD
        if ratio < threshold:
            candidates.append(
                {
                    "element_ref": cf["element_ref"],
                    "issue_type": "low_contrast",
                    "wcag_criterion": "1.4.3",
                    "computed_contrast_ratio": ratio,
                    "is_large_text": is_large,
                    "required_threshold": threshold,
                }
            )
    return candidates


def _compute_focus_indicator_candidates(css_findings: list[dict]) -> list[dict]:
    """Pure-code check: focus_indicator_visible == False -> candidate per SC 2.4.7."""
    candidates = []
    for cf in css_findings:
        if cf.get("focus_indicator_visible") is False:
            candidates.append(
                {
                    "element_ref": cf["element_ref"],
                    "issue_type": "missing_focus_indicator",
                    "wcag_criterion": "2.4.7",
                }
            )
    return candidates


CANDIDATE_SYSTEM_PROMPT = """You are an accessibility auditor. You will be given a list \
of accessibility PROBLEMS THAT HAVE ALREADY BEEN DETECTED AND CONFIRMED by deterministic \
code (contrast ratios and focus-indicator checks were computed directly from the page's \
computed styles, not estimated). Do NOT recompute, second-guess, or re-derive the \
numbers — treat computed_contrast_ratio/required_threshold as ground truth.

Your job for each candidate is only to:
- write a concrete, non-generic evidence string (include the actual numbers given to you)
- assign a severity: "critical" | "serious" | "moderate" | "minor"
- assign a confidence float 0-1 (this should generally be high, e.g. 0.85-1.0, since the \
underlying measurement is exact code, not a guess)

You MUST only choose wcag_criterion values from this fixed list, but for these \
candidates the wcag_criterion is already given to you — use it as-is, do not change it:
{wcag_list}

Respond with ONLY a JSON array (no markdown fences, no preamble) of finding objects, \
each with exactly these fields:
  finding_id: "" (leave empty)
  element_ref: as given
  agent: "visual"
  issue_type: as given
  wcag_criterion: as given
  severity: your judgment
  evidence: concrete string including the actual ratio/threshold numbers given
  confidence: float 0-1
"""

SCREENSHOT_SYSTEM_PROMPT = """You are an accessibility auditor doing a qualitative visual \
review of a full-page screenshot taken at 200% zoom (used to check for reflow problems: \
overlapping text, content cut off or clipped, text rendered illegibly small even after \
zoom, or elements visually overlapping each other).

You are also given the list of element_refs known to exist on this page (from the ax \
tree / css findings) so you can reference a real element_ref in any finding — do not \
invent an element_ref that isn't in this list. If you cannot confidently tie a visual \
problem to one of the given element_refs, do not report it.

Only flag issues that map to one of these WCAG criteria — if what you see doesn't fit \
one of these, do not report it as a finding:
{wcag_list}

Respond with ONLY a JSON array (no markdown fences, no preamble) of finding objects, \
each with exactly these fields:
  finding_id: "" (leave empty)
  element_ref: must be one of the known element_refs given to you
  agent: "visual"
  issue_type: a short snake_case label for what you observed
  wcag_criterion: from the list above
  severity: "critical" | "serious" | "moderate" | "minor"
  evidence: concrete, non-generic description of what you actually see in the screenshot
  confidence: float 0-1

If there are no such issues, respond with an empty JSON array: []
"""


def _findings_from_candidates(candidates: list[dict]) -> list[dict]:
    if not candidates:
        return []

    findings: list[dict] = []
    wcag_list = _wcag_list_str()
    system_prompt = CANDIDATE_SYSTEM_PROMPT.format(wcag_list=wcag_list)

    for i in range(0, len(candidates), CANDIDATE_BATCH_SIZE):
        batch = candidates[i : i + CANDIDATE_BATCH_SIZE]
        user_content = "Pre-computed candidates:\n" + json.dumps(batch, indent=2)
        try:
            raw = call_llm(system_prompt, user_content)
        except Exception as e:  # noqa: BLE001
            logger.error("visual_agent: candidate batch call failed: %s", e)
            continue
        findings.extend(validate_findings(raw))

    return findings


def _findings_from_screenshot(
    zoom_screenshot_path: Optional[str], known_element_refs: list[str]
) -> list[dict]:
    if not zoom_screenshot_path:
        return []
    if not Path(zoom_screenshot_path).exists():
        logger.info(
            "visual_agent: zoom_screenshot_path %r not found on disk yet (Person 1 hasn't "
            "published it) — skipping screenshot pass for this run.",
            zoom_screenshot_path,
        )
        return []

    wcag_list = _wcag_list_str()
    system_prompt = SCREENSHOT_SYSTEM_PROMPT.format(wcag_list=wcag_list)
    user_content = "Known element_refs on this page:\n" + json.dumps(known_element_refs)

    try:
        raw = call_llm(system_prompt, user_content, images=[zoom_screenshot_path])
    except Exception as e:  # noqa: BLE001
        logger.error("visual_agent: screenshot call failed: %s", e)
        return []

    return validate_findings(raw)


def run(extraction: dict) -> list[dict]:
    """Entry point: takes a full extraction.schema.json-shaped dict, returns
    validated findings, agent="visual"."""
    css_findings = extraction.get("css_findings", [])
    zoom_screenshot_path = extraction.get("zoom_screenshot_path")
    known_element_refs = [cf["element_ref"] for cf in css_findings]

    candidates = _compute_contrast_candidates(css_findings)
    candidates += _compute_focus_indicator_candidates(css_findings)

    findings: list[dict] = []
    findings.extend(_findings_from_candidates(candidates))
    findings.extend(_findings_from_screenshot(zoom_screenshot_path, known_element_refs))
    return findings


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else str(
        _REPO_ROOT / "fixtures" / "extraction_broken_page_1.json"
    )
    with open(path, "r", encoding="utf-8") as f:
        extraction_data = json.load(f)

    results = run(extraction_data)
    print(json.dumps(results, indent=2))
