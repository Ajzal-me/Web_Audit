"""
extract.py — Playwright-based main extraction script.
"""

from __future__ import annotations
import argparse
import json
import logging
import os
import sys
from pathlib import Path
from playwright.async_api import async_playwright

# Add repo root to sys.path so we can import from extractor and baseline
_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from extractor.ax_tree import get_ax_tree
from extractor.css_snapshot import get_css_findings
from extractor.keyboard_sim import get_keyboard_sim
from extractor.screenshot_crop import capture_crops
from baseline.run_axe import run_axe

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("a11yagents.extractor.extract")

async def extract_page(page_path_or_url: str, output_path: str | None = None) -> dict:
    """
    Loads page, injects IDs, orchestrates extraction modules, and returns extraction dict.
    """
    # Resolve local HTML file to file:// URL if it is not a web URL
    if not (page_path_or_url.startswith("http://") or page_path_or_url.startswith("https://")):
        p = Path(page_path_or_url).resolve()
        if not p.exists():
            raise FileNotFoundError(f"Local file not found: {page_path_or_url}")
        url = p.as_uri()
        page_name = p.stem
    else:
        url = page_path_or_url
        page_name = page_path_or_url.split("/")[-1] or "page"
        # strip query parameters
        page_name = page_name.split("?")[0]
        
    artifacts_dir = _REPO_ROOT / "test_pages" / "_artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    
    screenshot_path = artifacts_dir / f"zoom_{page_name}.png"
    
    async with async_playwright() as p:
        logger.info("Launching Chromium browser...")
        browser = await p.chromium.launch(headless=True)
        # Create a browser context with large viewport to capture details
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()
        
        logger.info("Navigating to: %s", url)
        await page.goto(url)
        # Wait for page load
        await page.wait_for_load_state("networkidle")
        
        # 1. Inject data-a11y-id BEFORE any other DOM reads
        logger.info("Injecting data-a11y-ids into DOM...")
        await page.evaluate("""
            () => {
                const elements = document.querySelectorAll('*');
                for (let i = 0; i < elements.length; i++) {
                    elements[i].setAttribute('data-a11y-id', 'a11y-' + i);
                }
            }
        """)
        
        # 2. Extract AX Tree via CDP
        ax_tree = await get_ax_tree(page)
        
        # 3. Extract CSS properties (contrast, focus rings)
        css_findings = await get_css_findings(page)
        
        # 4. Extract Screenshot Crops for images
        image_crops = await capture_crops(page, artifacts_dir)
        
        # 5. Extract Keyboard Sim parameters (requires ax_tree for interaction checks)
        keyboard_sim = await get_keyboard_sim(page, ax_tree)
        
        # 6. Capture 200% Zoom Screenshot
        logger.info("Capturing 200%% zoom screenshot...")
        await page.evaluate("document.body.style.zoom = '2.0'")
        # Wait a brief moment for zoom rendering
        await page.wait_for_timeout(300)
        await page.screenshot(path=str(screenshot_path), full_page=True)
        # Restore zoom
        await page.evaluate("document.body.style.zoom = '1.0'")
        
        # Assemble final extraction object
        extraction = {
            "page": page_path_or_url,
            "ax_tree": ax_tree,
            "css_findings": css_findings,
            "keyboard_sim": keyboard_sim,
            "image_crops": image_crops,
            "zoom_screenshot_path": str(screenshot_path.resolve()).replace('\\', '/')
        }
        
        # Also run axe baseline if needed, but we don't include it in the extraction schema.
        # Person 4's orchestrator will call run_axe.py and save raw violations.
        
        await browser.close()
        
    if output_path:
        out_p = Path(output_path).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(extraction, f, indent=2)
        logger.info("Wrote extraction output to: %s", out_p)
        
    return extraction

def main() -> None:
    parser = argparse.ArgumentParser(description="Extract page layout and accessibility metadata.")
    parser.add_argument("page", help="URL or path to local HTML file to extract.")
    parser.add_argument("--output", help="Path to write extraction JSON output.")
    args = parser.parse_argument_group().parser.parse_args() if len(sys.argv) > 1 else parser.parse_args(args=["--help"])
    
    import asyncio
    asyncio.run(extract_page(args.page, args.output))

if __name__ == "__main__":
    # If run directly without arguments, show help
    if len(sys.argv) < 2:
        print("Usage: python extractor/extract.py <url_or_path> [--output <json_path>]")
        sys.exit(1)
        
    import asyncio
    # Handle sys.argv manually to avoid argument conflicts
    page_arg = sys.argv[1]
    out_arg = None
    if "--output" in sys.argv:
        try:
            out_arg = sys.argv[sys.argv.index("--output") + 1]
        except IndexError:
            pass
            
    asyncio.run(extract_page(page_arg, out_arg))
