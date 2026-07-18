"""
orchestrator.py — Main orchestration entry point.
Flow: extract() -> run agents (LangGraph) -> run Axe & normalize -> synthesis -> validate & write reports.
"""

from __future__ import annotations
import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Ensure workspace root is in sys.path
_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from extractor.extract import extract_page
from agents.agent_graph import run_agent_workflow
from agents.synthesis_agent import synthesize

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("a11yagents.orchestrator")

async def orchestrate(page_path_or_url: str, output_path: str) -> None:
    logger.info("========================================")
    logger.info("Starting Web Accessibility Audit Pipeline")
    logger.info("Target: %s", page_path_or_url)
    logger.info("========================================")
    
    # 1. Run browser extraction and Axe baseline
    logger.info("[Step 1/4] Running extraction and Axe baseline...")
    extraction = await extract_page(page_path_or_url, include_axe=True)
    
    # 2. Run LangGraph agents
    logger.info("[Step 2/4] Running LangGraph agent workflow...")
    agent_findings = run_agent_workflow(extraction)
    
    # 3. Retrieve normalized Axe findings
    axe_findings = extraction.get("_axe_findings", [])
    logger.info("Axe-core baseline found %d standardized issues", len(axe_findings))
    logger.info("LangGraph agents found %d issues", len(agent_findings))
    
    # 4. Perform synthesis and merge
    logger.info("[Step 3/4] Synthesizing all findings...")
    all_findings = agent_findings + axe_findings
    report = synthesize(page_path_or_url, all_findings)
    
    # Write main report
    out_p = Path(output_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)
    with open(out_p, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    logger.info("[Step 4/4] Main report saved to: %s", out_p)
    
    # Generate and save comparison report
    agent_refs = set(f["element_ref"] for f in agent_findings)
    axe_refs = set(f["element_ref"] for f in axe_findings)
    
    overlapping_refs = agent_refs.intersection(axe_refs)
    agent_only_refs = agent_refs - axe_refs
    axe_only_refs = axe_refs - agent_refs
    
    agent_only_findings = [f for f in agent_findings if f["element_ref"] in agent_only_refs]
    axe_only_findings = [f for f in axe_findings if f["element_ref"] in axe_only_refs]
    overlapping_findings = [
        f for f in agent_findings + axe_findings if f["element_ref"] in overlapping_refs
    ]
    
    comparison = {
        "page": page_path_or_url,
        "summary": {
            "total_agent_findings": len(agent_findings),
            "total_axe_findings": len(axe_findings),
            "agent_only_count": len(agent_only_findings),
            "axe_only_count": len(axe_only_findings),
            "overlapping_count": len(overlapping_refs)
        },
        "agent_only_findings": agent_only_findings,
        "axe_only_findings": axe_only_findings,
        "overlapping_findings": overlapping_findings
    }
    
    comparison_path = out_p.parent / "report_with_axe_comparison.json"
    with open(comparison_path, "w", encoding="utf-8") as f:
        json.dump(comparison, f, indent=2)
    logger.info("Comparison report saved to: %s", comparison_path)
    logger.info("========================================")
    logger.info("Audit successfully completed!")

def main() -> None:
    parser = argparse.ArgumentParser(description="A11yAgents Orchestrator Pipeline")
    parser.add_argument("page", help="URL or local HTML path to audit.")
    parser.add_argument("--output", default="report.json", help="Path to save synthesis report.json (default: report.json).")
    args = parser.parse_args()
    
    asyncio.run(orchestrate(args.page, args.output))

if __name__ == "__main__":
    main()
