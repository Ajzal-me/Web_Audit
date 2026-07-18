"""
orchestrator.py — Main orchestration entry point for the A11yAgents pipeline.

Flow:
  1. extract_page(path, include_axe=True)
       -> Playwright browser session: injects data-a11y-ids, extracts AX tree,
          CSS findings, keyboard sim, image crops, AND runs axe-core baseline.
       -> Returns extraction dict with _axe_findings private key.

  2. run_full_pipeline(extraction, axe_violations, axe_selector_to_ref)
       -> LangGraph parallel graph: screen_reader + visual + motor + axe_baseline
          all fire simultaneously (fan-out), then synthesize_node joins them (fan-in).
       -> Returns {"findings": [...], "report": {...} | None}

  3. Write report.json (the synthesis report) and report_with_axe_comparison.json.
"""

from __future__ import annotations
import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from extractor.extract import extract_page
from agents.agent_graph import run_full_pipeline
from baseline.run_axe import run_axe
from baseline.normalize_axe import build_selector_to_ref_map, normalize_violations

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("a11yagents.orchestrator")


async def orchestrate(page_path_or_url: str, output_path: str) -> None:
    logger.info("=" * 48)
    logger.info("A11yAgents — Web Accessibility Audit Pipeline")
    logger.info("Target : %s", page_path_or_url)
    logger.info("=" * 48)

    # ── Step 1: Extraction (browser session) ──────────────────────────────────
    logger.info("[1/3] Running Playwright extraction...")
    extraction = await extract_page(page_path_or_url, include_axe=False)
    # extract_page with include_axe=False keeps the session fast and lets us
    # run axe separately with a clean page handle below — avoids double-launch.

    # ── Step 1b: Run axe-core in a second, minimal browser pass ───────────────
    logger.info("[1b/3] Running axe-core baseline scan...")
    raw_axe_violations: list[dict[str, Any]] = []
    selector_to_ref: dict[str, str] = {}
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(viewport={"width": 1280, "height": 800})
            pg = await ctx.new_page()

            # Resolve path to URL
            if not (page_path_or_url.startswith("http://") or page_path_or_url.startswith("https://")):
                p = Path(page_path_or_url).resolve()
                url = p.as_uri()
            else:
                url = page_path_or_url

            await pg.goto(url)
            await pg.wait_for_load_state("networkidle")

            # Inject data-a11y-ids so axe selectors resolve to our refs
            await pg.evaluate("""
                () => {
                    const elements = document.querySelectorAll('*');
                    for (let i = 0; i < elements.length; i++) {
                        elements[i].setAttribute('data-a11y-id', 'a11y-' + i);
                    }
                }
            """)

            raw_axe_violations = await run_axe(pg)
            selector_to_ref = await build_selector_to_ref_map(pg, raw_axe_violations)
            await browser.close()

        axe_findings = normalize_violations(raw_axe_violations, selector_to_ref)
        logger.info("Axe-core baseline: %d violations → %d normalized findings",
                    len(raw_axe_violations), len(axe_findings))
    except Exception as exc:
        logger.error("Axe-core baseline failed (continuing without it): %s", exc)
        axe_findings = []

    # ── Step 2: LangGraph multi-agent workflow + synthesis ────────────────────
    logger.info("[2/3] Running LangGraph agent workflow (4 agents + synthesis)...")
    pipeline_result = run_full_pipeline(
        extraction_data=extraction,
        axe_violations=raw_axe_violations if raw_axe_violations else None,
        axe_selector_to_ref=selector_to_ref if selector_to_ref else None,
    )

    report: dict[str, Any] | None = pipeline_result.get("report")
    all_findings: list[dict[str, Any]] = pipeline_result.get("findings", [])

    logger.info("Pipeline produced %d raw findings, report=%s",
                len(all_findings), "OK" if report else "None (schema validation failed)")

    # ── Step 3: Write outputs ─────────────────────────────────────────────────
    logger.info("[3/3] Writing output files...")
    out_p = Path(output_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)

    if report:
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        logger.info("Main report → %s", out_p)
    else:
        logger.warning("Synthesis returned None — writing raw findings as fallback report.")
        fallback = {
            "page": page_path_or_url,
            "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            "summary": {},
            "issues": all_findings,
        }
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(fallback, f, indent=2)
        logger.info("Fallback report → %s", out_p)

    # Partition findings for comparison report
    agent_names = {"screen_reader", "visual", "motor"}
    agent_findings = [f for f in all_findings if f.get("agent") in agent_names]
    axe_normalized = [f for f in all_findings if f.get("agent") == "axe_baseline"]

    agent_refs = {f["element_ref"] for f in agent_findings}
    axe_refs = {f["element_ref"] for f in axe_normalized}
    overlap_refs = agent_refs & axe_refs

    comparison = {
        "page": page_path_or_url,
        "summary": {
            "total_agent_findings": len(agent_findings),
            "total_axe_findings": len(axe_normalized),
            "agent_only_count": len(agent_refs - axe_refs),
            "axe_only_count": len(axe_refs - agent_refs),
            "overlapping_count": len(overlap_refs),
        },
        "agent_only_findings": [f for f in agent_findings if f["element_ref"] not in axe_refs],
        "axe_only_findings": [f for f in axe_normalized if f["element_ref"] not in agent_refs],
        "overlapping_findings": [f for f in all_findings if f["element_ref"] in overlap_refs],
    }

    comp_path = out_p.parent / "report_with_axe_comparison.json"
    with open(comp_path, "w", encoding="utf-8") as f:
        json.dump(comparison, f, indent=2)
    logger.info("Comparison report → %s", comp_path)

    logger.info("=" * 48)
    logger.info("Audit complete!")
    logger.info("  Agent findings : %d", len(agent_findings))
    logger.info("  Axe findings   : %d", len(axe_normalized))
    logger.info("  Agent-only     : %d  (missed by Axe)", len(agent_refs - axe_refs))
    logger.info("  Overlap        : %d", len(overlap_refs))
    logger.info("=" * 48)


def main() -> None:
    parser = argparse.ArgumentParser(description="A11yAgents Orchestrator")
    parser.add_argument("page", help="URL or local HTML path to audit.")
    parser.add_argument("--output", default="report.json",
                        help="Path to save synthesis report (default: report.json).")
    args = parser.parse_args()
    asyncio.run(orchestrate(args.page, args.output))


if __name__ == "__main__":
    main()
