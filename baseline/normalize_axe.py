"""
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
