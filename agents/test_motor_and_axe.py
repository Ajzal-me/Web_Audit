"""
agents/test_motor_and_axe.py

Person 3's integration check for the other two pieces: motor_agent.py (needs
GEMINI_API_KEY) and baseline/normalize_axe.py (pure function, no API key
needed — runs first so you get signal even without a key set up).

Usage:
    python agents/test_motor_and_axe.py [path/to/extraction.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent
sys.path.insert(0, str(_REPO_ROOT / "baseline"))

import motor_agent
from normalize_axe import normalize_violations

_DEFAULT_EXTRACTION = _REPO_ROOT / "fixtures" / "extraction_broken_page_1.json"
_DEFAULT_AXE_VIOLATIONS = _REPO_ROOT / "fixtures" / "mock_axe_violations.json"
_DEFAULT_AXE_MAPPING = _REPO_ROOT / "fixtures" / "mock_axe_selector_to_ref.json"


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
    # --- normalize_axe: pure function, no API key needed ---
    print("--- normalize_axe (no API key required) ---")
    violations = json.load(open(_DEFAULT_AXE_VIOLATIONS, "r", encoding="utf-8"))
    mapping = json.load(open(_DEFAULT_AXE_MAPPING, "r", encoding="utf-8"))
    axe_findings = normalize_violations(violations, mapping)
    _summarize("axe_baseline (normalized)", axe_findings)

    # --- motor_agent: needs GEMINI_API_KEY ---
    print("\n--- motor_agent (requires GEMINI_API_KEY) ---")
    extraction_path = Path(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_EXTRACTION
    with open(extraction_path, "r", encoding="utf-8") as f:
        extraction = json.load(f)
    motor_findings = motor_agent.run(extraction)
    _summarize("motor", motor_findings)

    print(f"\nTotal: {len(axe_findings)} axe_baseline + {len(motor_findings)} motor "
          f"= {len(axe_findings) + len(motor_findings)} findings")


if __name__ == "__main__":
    main()
