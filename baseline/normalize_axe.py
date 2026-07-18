"""
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
   data-a11y-id the rest of the pipeline uses.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger("a11yagents.baseline.normalize_axe")

# axe-core already uses the exact same 4 words we use for severity
AXE_IMPACT_TO_SEVERITY = {
    "critical": "critical",
    "serious": "serious",
    "moderate": "moderate",
    "minor": "minor",
}
DEFAULT_SEVERITY_FOR_UNKNOWN_IMPACT = "moderate"

# Maps common axe-core rule ids to the closest criterion in wcag22_criteria.json.
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
    "bypass": "1.3.1",
    "frame-title": "4.1.2",
    "checkboxgroup": "1.3.1",
    "radiogroup": "1.3.1",
    "focus-visible": "2.4.7",
}
DEFAULT_WCAG_FOR_UNKNOWN_RULE = "4.1.2"


def _map_wcag_criterion(rule_id: str, tags: list[str]) -> str:
    if rule_id in AXE_RULE_TO_WCAG:
        return AXE_RULE_TO_WCAG[rule_id]
    for tag in tags:
        if tag.startswith("wcag") and tag[4:].isdigit() and len(tag) == 7:
            digits = tag[4:]
            return f"{digits[0]}.{digits[1]}.{digits[2]}"
    logger.warning(
        "normalize_axe: no WCAG mapping for axe rule %r (tags=%s), defaulting to %s",
        rule_id, tags, DEFAULT_WCAG_FOR_UNKNOWN_RULE,
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
    """
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
                    selector, rule_id,
                )
                continue

            failure_summary = node.get("failureSummary", "").replace("\n", " ").strip()
            evidence = f"{help_text}. {failure_summary}".strip(". ").strip() + "."

            findings.append({
                "finding_id": str(uuid.uuid4()),
                "element_ref": element_ref,
                "agent": "axe_baseline",
                "issue_type": rule_id,
                "wcag_criterion": wcag_criterion,
                "severity": severity,
                "evidence": evidence,
                "confidence": 0.95,
            })

    logger.info("Axe normalization complete: produced %d standardized findings", len(findings))
    return findings


async def build_selector_to_ref_map(page: Any, violations: list[dict[str, Any]]) -> dict[str, str]:
    """
    Async, requires a real Playwright page handle. For every unique first-target
    CSS selector across all violations, resolves the element's data-a11y-id via DOM.
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


# Backward-compat alias for extract.py which called normalize_axe_violations(page, violations)
async def normalize_axe_violations(page: Any, violations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Async compat shim: builds selector map then normalizes. Called from extractor/extract.py."""
    selector_to_ref = await build_selector_to_ref_map(page, violations)
    return normalize_violations(violations, selector_to_ref)


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    _THIS_DIR = Path(__file__).resolve().parent
    _REPO_ROOT = _THIS_DIR.parent

    violations_path = (
        sys.argv[1] if len(sys.argv) > 1
        else str(_REPO_ROOT / "fixtures" / "mock_axe_violations.json")
    )
    mapping_path = (
        sys.argv[2] if len(sys.argv) > 2
        else str(_REPO_ROOT / "fixtures" / "mock_axe_selector_to_ref.json")
    )

    with open(violations_path, "r", encoding="utf-8") as f:
        violations_data = json.load(f)
    with open(mapping_path, "r", encoding="utf-8") as f:
        selector_map = json.load(f)

    results = normalize_violations(violations_data, selector_map)
    print(json.dumps(results, indent=2))
