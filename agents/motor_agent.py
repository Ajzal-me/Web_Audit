"""
motor_agent.py — Person 3's first inspection agent.

Input: the keyboard_sim object from an extraction.schema.json-shaped dict
(traversal_order, unreachable, illogical_jumps, trap_issues, small_targets —
real observed-behavior data captured by Playwright, not raw tabindex guesses),
plus ax_tree (role/name) so severity judgment can factor in what kind of
element is affected — an unreachable primary call-to-action button is worse
than an unreachable decorative element.

Mapping (deterministic in code, not left to the LLM):
    unreachable      -> SC 2.1.1 (Keyboard)
    illogical_jumps  -> SC 2.4.3 (Focus Order)
    trap_issues      -> SC 2.1.2 (No Keyboard Trap)
    small_targets    -> SC 2.5.8 (Target Size Minimum)

The LLM's job per candidate is only severity + evidence + confidence, using the
ax_tree context we hand it — it does not re-derive which WCAG criterion applies.

Output: a validated list of findings with "agent": "motor".
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from base_agent import call_llm, validate_findings, load_wcag_criteria

logger = logging.getLogger("a11yagents.motor_agent")

CANDIDATE_BATCH_SIZE = 10

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent


def _wcag_list_str() -> str:
    criteria = load_wcag_criteria()
    lines = [f"- {cid}: {c['title']} — {c['short_description']}" for cid, c in criteria.items()]
    return "\n".join(lines)


def _ax_lookup(ax_tree: list[dict]) -> dict:
    """element_ref -> {role, name} for quick context lookup while building candidates."""
    return {
        node["element_ref"]: {"role": node.get("role", ""), "name": node.get("name", "")}
        for node in ax_tree
    }


def _build_candidates(keyboard_sim: dict, ax_tree: list[dict]) -> list[dict]:
    """Pure-code translation of each raw keyboard_sim signal into a candidate
    dict with its WCAG criterion already assigned and ax_tree context attached."""
    ax_by_ref = _ax_lookup(ax_tree)
    candidates: list[dict] = []

    for ref in keyboard_sim.get("unreachable", []):
        candidates.append(
            {
                "element_ref": ref,
                "issue_type": "unreachable",
                "wcag_criterion": "2.1.1",
                "context": ax_by_ref.get(ref, {"role": "unknown", "name": ""}),
                "detail": "This element is interactive/focusable but never received keyboard focus during a full Tab-key traversal of the page.",
            }
        )

    for jump in keyboard_sim.get("illogical_jumps", []):
        ref = jump["element_ref"]
        candidates.append(
            {
                "element_ref": ref,
                "issue_type": "illogical_tab_order",
                "wcag_criterion": "2.4.3",
                "context": ax_by_ref.get(ref, {"role": "unknown", "name": ""}),
                "detail": jump.get("note", ""),
            }
        )

    for trap in keyboard_sim.get("trap_issues", []):
        ref = trap["element_ref"]
        candidates.append(
            {
                "element_ref": ref,
                "issue_type": "focus_trap",
                "wcag_criterion": "2.1.2",
                "context": ax_by_ref.get(ref, {"role": "unknown", "name": ""}),
                "detail": trap.get("note", ""),
            }
        )

    for target in keyboard_sim.get("small_targets", []):
        ref = target["element_ref"]
        candidates.append(
            {
                "element_ref": ref,
                "issue_type": "small_target",
                "wcag_criterion": "2.5.8",
                "context": ax_by_ref.get(ref, {"role": "unknown", "name": ""}),
                "detail": f"Target size measured at {target.get('width')}x{target.get('height')}px "
                f"(minimum required is 24x24 CSS pixels).",
            }
        )

    return candidates


CANDIDATE_SYSTEM_PROMPT = """You are an accessibility auditor reviewing keyboard/motor-\
accessibility problems THAT HAVE ALREADY BEEN DETECTED AND CONFIRMED by deterministic \
code from real simulated keyboard interaction (actual Tab-key traversal, actual \
bounding-box measurements) — not estimated or guessed. Do NOT second-guess whether the \
problem exists or which WCAG criterion applies; both are already given to you and \
correct.

Your job for each candidate is only to:
- assign a severity: "critical" | "serious" | "moderate" | "minor" — use the given \
`context` (the element's accessibility role and name) to judge impact. An unreachable \
or trapped PRIMARY action (e.g. role "button"/"link" with a name suggesting a checkout, \
submit, or navigation action) is more severe than the same problem on a decorative or \
minor element (e.g. an empty-name element, a low-importance icon).
- write a concrete, non-generic evidence string that references the actual role/name/\
detail given (not a generic restatement of the issue_type).
- assign a confidence float 0-1 (this should generally be high, e.g. 0.85-1.0, since \
the underlying measurement is exact simulated behavior, not a guess).

You MUST only choose wcag_criterion values from this fixed list, but for these \
candidates the wcag_criterion is already given to you — use it as-is, do not change it:
{wcag_list}

Respond with ONLY a JSON array (no markdown fences, no preamble) of finding objects, \
each with exactly these fields:
  finding_id: "" (leave empty)
  element_ref: as given
  agent: "motor"
  issue_type: as given
  wcag_criterion: as given
  severity: your judgment
  evidence: concrete string referencing the actual role/name/detail given
  confidence: float 0-1
"""


def _findings_from_candidates(candidates: list[dict]) -> list[dict]:
    if not candidates:
        return []

    findings: list[dict] = []
    wcag_list = _wcag_list_str()
    system_prompt = CANDIDATE_SYSTEM_PROMPT.format(wcag_list=wcag_list)

    for i in range(0, len(candidates), CANDIDATE_BATCH_SIZE):
        batch = candidates[i : i + CANDIDATE_BATCH_SIZE]
        user_content = "Pre-detected keyboard/motor-accessibility candidates:\n" + json.dumps(
            batch, indent=2
        )
        raw = call_llm(system_prompt, user_content)
        findings.extend(validate_findings(raw))

    return findings


def run(extraction: dict) -> list[dict]:
    """Entry point: takes a full extraction.schema.json-shaped dict, returns
    validated findings, agent="motor"."""
    keyboard_sim = extraction.get("keyboard_sim", {})
    ax_tree = extraction.get("ax_tree", [])

    candidates = _build_candidates(keyboard_sim, ax_tree)
    return _findings_from_candidates(candidates)


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else str(
        _REPO_ROOT / "fixtures" / "extraction_broken_page_1.json"
    )
    with open(path, "r", encoding="utf-8") as f:
        extraction_data = json.load(f)

    results = run(extraction_data)
    print(json.dumps(results, indent=2))
