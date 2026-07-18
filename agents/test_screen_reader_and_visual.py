"""
agents/test_screen_reader_and_visual.py

Person 2's own integration check, independent of anyone else's code. Loads a
fixture extraction JSON and runs both screen_reader_agent and visual_agent,
printing validated findings.

Usage:
    python agents/test_screen_reader_and_visual.py [path/to/extraction.json]

Requires GEMINI_API_KEY (or GOOGLE_API_KEY) to be set in the environment (real
LLM calls are made — this is an integration check, not a unit test with mocked
responses). Get a free key at https://aistudio.google.com.

Acceptance check from the plan:
  - Running against fixtures/extraction_broken_page_1.json should yield
    schema-valid findings from both agents with real (in-list) WCAG criteria
    and concrete evidence strings.
  - Running against fixtures/extraction_good_page_1.json should yield few/no
    findings.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import screen_reader_agent
import visual_agent

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent
_DEFAULT_FIXTURE = _REPO_ROOT / "fixtures" / "extraction_broken_page_1.json"


def _summarize(label: str, findings: list[dict]) -> None:
    print(f"\n=== {label}: {len(findings)} finding(s) ===")
    for f in findings:
        print(
            f"  [{f.get('severity', '?'):8s}] {f.get('agent', '?'):14s} "
            f"{f.get('element_ref', '?'):8s} {f.get('issue_type', '?'):22s} "
            f"WCAG {f.get('wcag_criterion', '?')}  conf={f.get('confidence', '?')}\n"
            f"      evidence: {f.get('evidence', '')}"
        )


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_FIXTURE
    print(f"Loading fixture: {path}")
    with open(path, "r", encoding="utf-8") as f:
        extraction = json.load(f)

    sr_findings = screen_reader_agent.run(extraction)
    _summarize("screen_reader_agent", sr_findings)

    visual_findings = visual_agent.run(extraction)
    _summarize("visual_agent", visual_findings)

    total = len(sr_findings) + len(visual_findings)
    print(f"\nTotal findings: {total}")


if __name__ == "__main__":
    main()
