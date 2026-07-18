"""
synthesis_agent.py — Groups findings by element and compiles the final report.
Provides a deterministic Python-based merge algorithm as a baseline.
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("a11yagents.agents.synthesis_agent")

SEVERITY_RANKS = {"critical": 3, "serious": 2, "moderate": 1, "minor": 0}
RANK_TO_SEVERITY = {3: "critical", 2: "serious", 1: "moderate", 0: "minor"}

# Maps raw issue_type tokens (from agents or axe rule IDs) to human-readable phrases
ISSUE_TYPE_LABELS: dict[str, str] = {
    "missing_alt": "missing or empty alt text",
    "meaningless_alt": "a meaningless filename used as alt text",
    "unlabeled_control": "an unlabeled interactive control",
    "meaningless_link_text": "meaningless link text (e.g. 'click here')",
    "heading_structure": "a broken heading hierarchy",
    "low_contrast": "insufficient color contrast",
    "no_focus_ring": "no visible keyboard focus indicator",
    "small_target": "a touch/click target that is too small",
    "keyboard_trap": "a keyboard focus trap",
    # Axe-core rule IDs (underscored)
    "image_alt": "a missing image alt attribute",
    "button_name": "an unlabeled button with no accessible name",
    "link_name": "a link with no accessible name",
    "label": "a form input with no associated label",
    "color_contrast": "insufficient color contrast ratio",
    "heading_order": "headings that skip levels (e.g. h1 → h3 with no h2)",
    "aria_input_field_name": "an ARIA input field with no accessible name",
    "frame_title": "an iframe with no title attribute",
}

# Maps WCAG criterion IDs to short, action-oriented fix instructions
WCAG_PLAIN: dict[str, str] = {
    "1.1.1": "add a meaningful alt attribute describing the content or purpose of the element",
    "1.3.1": "use semantic HTML elements and ARIA roles so structure is conveyed programmatically",
    "1.4.3": "increase the contrast ratio between text and background to at least 4.5:1",
    "1.4.11": "ensure non-text UI components have at least 3:1 contrast against adjacent colors",
    "2.1.1": "ensure all functionality can be accessed and operated using only a keyboard",
    "2.1.2": "ensure users can move keyboard focus away from this element using the Tab or Escape key",
    "2.4.3": "ensure focusable elements receive focus in a logical order that matches visual layout",
    "2.4.4": "replace vague link text with a description of the link destination or purpose",
    "2.4.7": "add a visible :focus style (outline, border, or background change) to this element",
    "2.5.8": "increase the padding or size of this element's click/touch target to at least 24×24 CSS pixels",
    "4.1.2": "add a visible <label>, aria-label, or aria-labelledby so assistive technologies can read its name",
}


def _clean_evidence(raw: str) -> str:
    """Strip verbose Axe boilerplate ('Fix any of the following:...') from evidence strings."""
    if not raw:
        return ""
    if "Fix any of the following" in raw:
        lines = [
            line.strip()
            for line in raw.split("\n")
            if line.strip() and not line.strip().startswith("Fix any")
        ]
        return lines[0] if lines else ""
    return raw


def _format_description(group: list[dict]) -> str:
    """Produce a clean, plain-English description from a group of findings on the same element."""
    sentences: list[str] = []
    seen: set[tuple[str, str]] = set()

    for f in group:
        issue_type = f.get("issue_type", "")
        label = ISSUE_TYPE_LABELS.get(issue_type, issue_type.replace("_", " "))
        core = _clean_evidence(f.get("evidence", ""))

        dedup_key = (issue_type, core[:60])
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        if core:
            sentences.append(f"This element has {label} — {core}.")
        else:
            agent = f.get("agent", "auditor").replace("_", " ").replace("axe baseline", "the automated scan")
            sentences.append(f"This element has {label}, flagged by {agent}.")

    return " ".join(sentences)


def _format_fix(group: list[dict]) -> str:
    """Produce concise, actionable fix instructions based on WCAG criteria violated."""
    fixes: list[str] = []
    seen_criteria: set[str] = set()

    for f in group:
        criterion = f.get("wcag_criterion", "")
        if criterion in seen_criteria:
            continue
        seen_criteria.add(criterion)
        instruction = WCAG_PLAIN.get(criterion, f"comply with WCAG {criterion}")
        fixes.append(f"• (WCAG {criterion}) {instruction.capitalize()}.")

    return " ".join(fixes)


def synthesize(page: str, findings: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Groups findings by element_ref and compiles a final report.
    Returns a dict matching schemas/report.schema.json.

    Algorithm:
      1. Group all findings by element_ref.
      2. For each group, take the maximum severity.
      3. If multiple distinct agents flagged the same element, boost severity by 1 rank.
      4. Format clean plain-language descriptions and fix instructions.
      5. Sort issues by final severity, descending.
    """
    logger.info("Starting synthesis for page: %s with %d total findings", page, len(findings))

    # 1. Group by element_ref
    by_element: dict[str, list[dict[str, Any]]] = {}
    for f in findings:
        ref = f.get("element_ref", "unknown")
        by_element.setdefault(ref, []).append(f)

    issues: list[dict[str, Any]] = []
    summary = {"critical": 0, "serious": 0, "moderate": 0, "minor": 0}

    # 2. Process each element group
    for ref, group in by_element.items():
        criteria = sorted(set(f["wcag_criterion"] for f in group))
        agents = sorted(set(f["agent"] for f in group))

        # Take the highest severity reported for this element
        max_rank = max(SEVERITY_RANKS.get(f.get("severity", "minor"), 0) for f in group)

        # Compound issue logic: multiple distinct agents → bump severity by 1
        if len(agents) > 1 and max_rank < 3:
            max_rank += 1
            logger.info(
                "Compounding issue for element %s: boosting to %s (flagged by: %s)",
                ref, RANK_TO_SEVERITY[max_rank], ", ".join(agents)
            )

        final_severity = RANK_TO_SEVERITY[max_rank]
        summary[final_severity] += 1

        evidence = [_clean_evidence(f.get("evidence", "")) for f in group]

        issues.append({
            "element_ref": ref,
            "wcag_criteria": criteria,
            "severity": final_severity,
            "agents_flagging": agents,
            "plain_language_description": _format_description(group),
            "recommended_fix": _format_fix(group),
            "evidence": [e for e in evidence if e],  # strip empty strings
        })

    # 3. Sort issues by severity descending (critical first)
    issues.sort(key=lambda x: SEVERITY_RANKS.get(x["severity"], 0), reverse=True)

    return {
        "page": page,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": summary,
        "issues": issues,
    }
