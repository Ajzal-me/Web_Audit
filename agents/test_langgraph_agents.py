"""
test_langgraph_agents.py — Script to test running the LangGraph agent workflow against a JSON extraction fixture.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

# Ensure agents directory is in path
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from agent_graph import run_agent_workflow

def _summarize(findings: list[dict]) -> None:
    print(f"\n=== LangGraph Agent Workflow: {len(findings)} finding(s) ===")
    for f in findings:
        print(
            f"  [{f.get('severity', '?'):8s}] {f.get('agent', '?'):14s} "
            f"{f.get('element_ref', '?'):8s} {f.get('issue_type', '?'):22s} "
            f"WCAG {f.get('wcag_criterion', '?')}  conf={f.get('confidence', '?')}\n"
            f"      evidence: {f.get('evidence', '')}"
        )

def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else _THIS_DIR.parent / "fixtures" / "extraction_broken_page_1.json"
    print(f"Loading fixture: {path}")
    
    with open(path, "r", encoding="utf-8") as f:
        extraction = json.load(f)
        
    findings = run_agent_workflow(extraction)
    _summarize(findings)
    print(f"\nTotal findings: {len(findings)}")

if __name__ == "__main__":
    main()
