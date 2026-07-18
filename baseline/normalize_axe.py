"""
<<<<<<< HEAD
normalize_axe.py — Normalizes raw axe-core violations into finding.schema.json records.
"""

from __future__ import annotations
import logging
import uuid
from typing import Any
from playwright.async_api import Page

logger = logging.getLogger("a11yagents.baseline.normalize_axe")

# Map of common Axe rule IDs to closest WCAG 2.2 criteria in our wcag22_criteria.json
RULE_TO_WCAG_MAP = {
    "color-contrast": "1.4.3",
    "image-alt": "1.1.1",
    "link-name": "2.4.4",
    "label": "4.1.2",
    "aria-input-field-name": "4.1.2",
    "focus-visible": "2.4.7",
    "target-size": "2.5.8",
    "bypass": "1.3.1",
    "heading-order": "1.3.1",
    "area-alt": "1.1.1",
    "input-image-alt": "1.1.1",
    "button-name": "4.1.2",
    "checkboxgroup": "1.3.1",
    "radiogroup": "1.3.1",
    "frame-title": "4.1.2",
}

def _resolve_wcag_criterion(rule_id: str, tags: list[str]) -> str:
    """Helper to resolve a WCAG criterion ID from Axe rule ID or tags."""
    if rule_id in RULE_TO_WCAG_MAP:
        return RULE_TO_WCAG_MAP[rule_id]
        
    # Fallback: check tags for specific patterns like 'wcag143' or 'wcag111'
    for tag in tags:
        if tag.startswith("wcag") and tag[4:].isdigit():
            # e.g., 'wcag143' -> '1.4.3'
            digits = tag[4:]
            if len(digits) >= 3:
                return f"{digits[0]}.{digits[1]}.{digits[2]}"
                
    # Default fallback
    return "1.3.1"

def _map_severity(impact: str | None) -> str:
    """Map Axe impact levels to standard severities."""
    if impact in ("critical", "serious", "moderate", "minor"):
        return impact
    return "moderate"  # fallback

async def normalize_axe_violations(page: Page, violations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Translates raw axe-core violations into unified finding records.
    Uses Playwright page to resolve CSS selectors back to 'data-a11y-id'.
    """
    logger.info("Normalizing %d raw Axe violations...", len(violations))
    findings: list[dict[str, Any]] = []
    
    for rule in violations:
        rule_id = rule.get("id", "")
        impact = rule.get("impact")
        tags = rule.get("tags", [])
        wcag_id = _resolve_wcag_criterion(rule_id, tags)
        severity = _map_severity(impact)
        
        for node in rule.get("nodes", []):
            targets = node.get("target", [])
            if not targets:
                continue
                
            # Usually targets is a list of selectors, take the first/deepest one
            selector = targets[0]
            
            # Resolve data-a11y-id from DOM via Playwright evaluate
            element_ref = None
            try:
                element_ref = await page.evaluate("""
                    (sel) => {
                        const el = document.querySelector(sel);
                        return el ? el.getAttribute('data-a11y-id') : null;
                    }
                """, selector)
            except Exception as e:
                logger.warning("Could not resolve selector %r in DOM: %s", selector, e)
                
            if not element_ref:
                logger.debug("Skipping Axe violation target %r: no data-a11y-id mapping", selector)
                continue
                
            evidence = node.get("failureSummary", f"Axe-core violation: {rule_id}")
            
            findings.append({
                "finding_id": str(uuid.uuid4()),
                "element_ref": element_ref,
                "agent": "axe_baseline",
                "issue_type": rule_id.replace("-", "_"),
                "wcag_criterion": wcag_id,
                "severity": severity,
                "evidence": evidence,
                "confidence": 1.0
            })
            
    logger.info("Axe normalization complete: produced %d standardized findings", len(findings))
    return findings
=======
baseline/normalize_axe.py — Person 3's axe-core normalization.

Takes raw axe-core violation objects (Person 1's run_axe.py output — the
standard axe-core `results.violations` array: each item has `id`, `impact`,
`tags`, `description`, `help`, and `nodes[]` where each node has `target`
(a list of CSS selectors) and `failureSummary`) and reshapes them into
finding.schema.json shape with "agent": "axe_baseline".

Two separable concerns, deliberately split so the rule-mapping logic can be
fully built and tested against a mocked axe JSON fixture without a live
browser:

1. normalize_violations(violations, selector_to_ref) — pure, synchronous,
   fully testable offline. Does the rule-id -> WCAG-criterion mapping and
   impact -> severity mapping.
2. build_selector_to_ref_map(page, violations) — async, requires a real
   Playwright page handle. Resolves each axe CSS-selector target back to the
   data-a11y-id the rest of the pipeline uses. This is the one piece that
   must be wired to Person 1's real page object at integration time; nothing
   else in this file needs to change when that happens.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("a11yagents.baseline.normalize_axe")

# axe-core already uses the exact same 4 words we use for severity, so this
# is an identity map in practice — kept explicit in case axe ever reports an
# impact value outside our enum (e.g. axe's "minor"/"moderate"/"serious"/
# "critical" are the only ones we've seen, but unknown values fall back to
# "moderate" rather than crashing).
AXE_IMPACT_TO_SEVERITY = {
    "critical": "critical",
    "serious": "serious",
    "moderate": "moderate",
    "minor": "minor",
}
DEFAULT_SEVERITY_FOR_UNKNOWN_IMPACT = "moderate"

# Maps common axe-core rule ids to the closest criterion in wcag22_criteria.json.
# This list only needs to cover rules that actually show up in axe's default
# ruleset for the kind of test pages this project audits — extend as new rule
# ids are observed in real axe output.
AXE_RULE_TO_WCAG = {
    "color-contrast": "1.4.3",
    "color-contrast-enhanced": "1.4.3",
    "image-alt": "1.1.1",
    "input-image-alt": "1.1.1",
    "area-alt": "1.1.1",
    "object-alt": "1.1.1",
    "label": "4.1.2",
    "form-field-multiple-labels": "4.1.2",
    "aria-input-field-name": "4.1.2",
    "button-name": "4.1.2",
    "link-name": "2.4.4",
    "aria-command-name": "4.1.2",
    "heading-order": "1.3.1",
    "empty-heading": "2.4.6",
    "page-has-heading-one": "1.3.1",
    "focus-order-semantics": "2.4.3",
    "tabindex": "2.4.3",
    "focusable-content": "2.1.1",
    "no-focusable-content": "2.1.1",
    "target-size": "2.5.8",
    "non-text-contrast": "1.4.11",
    "aria-valid-attr-value": "4.1.2",
    "aria-valid-attr": "4.1.2",
    "aria-roles": "4.1.2",
    "duplicate-id-active": "4.1.2",
    "duplicate-id-aria": "4.1.2",
}
DEFAULT_WCAG_FOR_UNKNOWN_RULE = "4.1.2"  # closest general-purpose fallback (Name, Role, Value)


def _map_wcag_criterion(rule_id: str, tags: list[str]) -> str:
    if rule_id in AXE_RULE_TO_WCAG:
        return AXE_RULE_TO_WCAG[rule_id]
    # Fall back to scanning tags for a wcagNNN-style tag we recognize the shape of.
    for tag in tags:
        if tag.startswith("wcag") and tag[4:].isdigit() and len(tag) == 7:
            # e.g. "wcag143" -> "1.4.3"
            digits = tag[4:]
            candidate = f"{digits[0]}.{digits[1]}.{digits[2]}"
            return candidate
    logger.warning(
        "normalize_axe: no WCAG mapping for axe rule %r (tags=%s), defaulting to %s",
        rule_id,
        tags,
        DEFAULT_WCAG_FOR_UNKNOWN_RULE,
    )
    return DEFAULT_WCAG_FOR_UNKNOWN_RULE


def normalize_violations(
    violations: list[dict[str, Any]], selector_to_ref: dict[str, str]
) -> list[dict[str, Any]]:
    """
    Pure, synchronous. Reshapes raw axe violations into finding.schema.json-shaped
    dicts. selector_to_ref maps an axe node's first CSS-selector target string to
    the data-a11y-id it resolves to (built by build_selector_to_ref_map at
    integration time, or hand-written for a mock fixture during development).

    Nodes whose selector isn't in selector_to_ref are skipped (logged), rather
    than emitting a finding with an invalid element_ref that would fail
    finding.schema.json's pattern validation downstream.
    """
    import uuid

    findings: list[dict[str, Any]] = []

    for violation in violations:
        rule_id = violation.get("id", "")
        tags = violation.get("tags", [])
        wcag_criterion = _map_wcag_criterion(rule_id, tags)
        severity = AXE_IMPACT_TO_SEVERITY.get(
            violation.get("impact", ""), DEFAULT_SEVERITY_FOR_UNKNOWN_IMPACT
        )
        help_text = violation.get("help", "") or violation.get("description", "")

        for node in violation.get("nodes", []):
            targets = node.get("target", [])
            selector = targets[0] if targets else None
            if not selector:
                continue

            element_ref = selector_to_ref.get(selector)
            if not element_ref:
                logger.warning(
                    "normalize_axe: no data-a11y-id resolution for selector %r (rule %s) — skipping",
                    selector,
                    rule_id,
                )
                continue

            failure_summary = node.get("failureSummary", "").replace("\n", " ").strip()
            evidence = f"{help_text}. {failure_summary}".strip(". ").strip() + "."

            findings.append(
                {
                    "finding_id": str(uuid.uuid4()),
                    "element_ref": element_ref,
                    "agent": "axe_baseline",
                    "issue_type": rule_id,
                    "wcag_criterion": wcag_criterion,
                    "severity": severity,
                    "evidence": evidence,
                    # axe-core is a deterministic static-analysis tool, not a
                    # probabilistic judgment call, so confidence is fixed high.
                    "confidence": 0.95,
                }
            )

    return findings


async def build_selector_to_ref_map(page: Any, violations: list[dict[str, Any]]) -> dict[str, str]:
    """
    Async, requires a real Playwright `page` handle — this is the piece that
    gets wired to Person 1's real extraction run at integration time. For
    every unique first-target CSS selector across all violations, resolves
    the element's data-a11y-id via the DOM.

    Not exercised by test_normalize_axe.py (which uses a mocked
    selector_to_ref dict instead) — exercise this for real once a live page
    object is available in the orchestrator.
    """
    selector_to_ref: dict[str, str] = {}
    seen: set[str] = set()

    for violation in violations:
        for node in violation.get("nodes", []):
            targets = node.get("target", [])
            if not targets:
                continue
            selector = targets[0]
            if selector in seen:
                continue
            seen.add(selector)
            try:
                ref = await page.eval_on_selector(
                    selector, "el => el.getAttribute('data-a11y-id')"
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "build_selector_to_ref_map: could not resolve selector %r: %s", selector, e
                )
                continue
            if ref:
                selector_to_ref[selector] = ref

    return selector_to_ref


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    _THIS_DIR = Path(__file__).resolve().parent
    _REPO_ROOT = _THIS_DIR.parent

    violations_path = (
        sys.argv[1] if len(sys.argv) > 1 else str(_REPO_ROOT / "fixtures" / "mock_axe_violations.json")
    )
    mapping_path = (
        sys.argv[2] if len(sys.argv) > 2 else str(_REPO_ROOT / "fixtures" / "mock_axe_selector_to_ref.json")
    )

    with open(violations_path, "r", encoding="utf-8") as f:
        violations_data = json.load(f)
    with open(mapping_path, "r", encoding="utf-8") as f:
        selector_map = json.load(f)

    results = normalize_violations(violations_data, selector_map)
    print(json.dumps(results, indent=2))
>>>>>>> 0835fb10269ca5c48eb5e12bd3a96ad7762cbc16
