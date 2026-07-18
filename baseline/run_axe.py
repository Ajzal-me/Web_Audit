"""
run_axe.py — Module for running axe-core in the browser context.
"""

from __future__ import annotations
import logging
from typing import Any
from playwright.async_api import Page

logger = logging.getLogger("a11yagents.baseline.run_axe")

async def run_axe(page: Page) -> list[dict[str, Any]]:
    """
    Injects axe-core from CDN and executes axe.run().
    Returns the list of raw violations.
    """
    logger.info("Injecting axe-core script via CDN...")
    try:
        await page.add_script_tag(url="https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.8.2/axe.min.js")
    except Exception as e:
        logger.error("Failed to inject axe-core: %s. Trying fallback local inject if available...", e)
        # We can try fallback to a local copy if we want, but CDN is fine for now
        raise
        
    logger.info("Running axe.run() in browser...")
    results = await page.evaluate("() => axe.run()")
    violations = results.get("violations", [])
    logger.info("Axe execution complete. Violations found: %d", len(violations))
    return violations
