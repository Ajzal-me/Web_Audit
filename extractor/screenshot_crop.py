"""
screenshot_crop.py — Module for capturing visual crops of images and icon-only controls.
"""

from __future__ import annotations
import logging
from pathlib import Path
from typing import Any
from playwright.async_api import Page

logger = logging.getLogger("a11yagents.extractor.screenshot_crop")

async def capture_crops(page: Page, base_artifacts_dir: Path) -> list[dict[str, Any]]:
    """
    Finds images and icon-only controls, takes a cropped screenshot of each,
    and returns a list of crop info dictionary objects matching the schema.
    """
    logger.info("Identifying images and icon-only controls for screenshot crops...")
    
    # Identify candidates in the browser page
    candidates = await page.evaluate("""
        () => {
            const list = [];
            
            // 1. Image elements and SVGs with graphic role
            const imgs = document.querySelectorAll('img, svg, [role="img"]');
            for (const el of imgs) {
                if (!(el.offsetWidth > 0 || el.offsetHeight > 0)) continue;
                
                const ref = el.getAttribute('data-a11y-id');
                if (ref) {
                    let claimedAlt = '';
                    if (el.tagName.toLowerCase() === 'img') {
                        claimedAlt = el.getAttribute('alt') || '';
                    } else {
                        claimedAlt = el.getAttribute('aria-label') || el.getAttribute('title') || '';
                    }
                    list.push({ element_ref: ref, claimed_alt: claimedAlt.trim() });
                }
            }
            
            // 2. Icon-only controls (interactive elements with no visible text content)
            const controls = document.querySelectorAll('button, a, [role="button"], [role="link"]');
            for (const el of controls) {
                if (!(el.offsetWidth > 0 || el.offsetHeight > 0)) continue;
                
                const ref = el.getAttribute('data-a11y-id');
                if (ref) {
                    const text = el.innerText || '';
                    if (text.trim().length === 0) {
                        const claimedAlt = el.getAttribute('aria-label') || el.getAttribute('title') || '';
                        // Avoid duplicates if the control itself contains an img that we already added
                        if (!list.some(item => item.element_ref === ref)) {
                            list.push({ element_ref: ref, claimed_alt: claimedAlt.trim() });
                        }
                    }
                }
            }
            
            return list;
        }
    """)
    
    crops_dir = base_artifacts_dir / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)
    
    image_crops: list[dict[str, Any]] = []
    
    for item in candidates:
        ref = item["element_ref"]
        claimed_alt = item["claimed_alt"]
        crop_file = crops_dir / f"{ref}.png"
        
        try:
            locator = page.locator(f'[data-a11y-id="{ref}"]')
            if await locator.is_visible():
                # Capture the element screenshot
                await locator.screenshot(path=str(crop_file))
                image_crops.append({
                    "element_ref": ref,
                    # We will store the path relative to the workspace root or absolute path
                    "crop_path": str(crop_file.resolve()).replace('\\', '/'),
                    "claimed_alt": claimed_alt
                })
                logger.info("Captured screenshot crop for %s -> %s", ref, crop_file.name)
        except Exception as e:
            logger.warning("Could not capture screenshot crop for element %s: %s", ref, e)
            continue
            
    return image_crops
