"""
agents/test_synthesis.py

Person 3's own integration check, independent of anyone else's code. Loads
mock_data/sample_findings.json, runs synthesis_agent, and prints/validates the
resulting report.

Usage:
    python agents/test_synthesis.py [path/to/findings.json]

Requires GEMINI_API_KEY (or GOOGLE_API_KEY) to be set — real LLM calls are
made.

ACCEPTANCE CHECK (per the plan): synthesis_agent, run against the hand-written
mock_data/sample_findings.json, should produce a schema-valid report.json
where an element flagged by 2+ agents shows up ONCE with agents_flagging
listing all of them — not as duplicate entries. This script checks that
automatically at the end.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import synthesis_agent

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent
_DEFAULT_FINDINGS = _REPO_ROOT / "mock_data" / "sample_findings.json"


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_FINDINGS
    print(f"Loading findings: {path}")
    with open(path, "r", encoding="utf-8") as f:
        findings = json.load(f)

    input_ref_counts = Counter(f["element_ref"] for f in findings)
    compounding_refs = {ref for ref, count in input_ref_counts.items() if count > 1}
    print(f"Input: {len(findings)} findings across {len(input_ref_counts)} distinct elements "
          f"({len(compounding_refs)} compounding: {sorted(compounding_refs)})")

    report = synthesis_agent.run(findings, page=str(path))

    if report is None:
        print("\nFAILED: synthesis_agent.run() returned None (schema validation failed).")
        sys.exit(1)

    print(f"\n=== Report: {len(report['issues'])} issue(s) ===")
    for issue in report["issues"]:
        print(
            f"  #{issue['priority_rank']:<2d} [{issue['severity']:8s}] {issue['element_ref']:8s} "
            f"agents={issue['agents_flagging']} wcag={issue['wcag_criteria']}\n"
            f"      desc: {issue['plain_language_description']}\n"
            f"      fix:  {issue['recommended_fix']}"
        )

    # --- Acceptance check ---
    print("\n=== Acceptance check ===")
    output_refs = [issue["element_ref"] for issue in report["issues"]]
    output_ref_counts = Counter(output_refs)
    duplicated_in_output = {ref for ref, count in output_ref_counts.items() if count > 1}

    ok = True
    if duplicated_in_output:
        print(f"FAIL: these element_refs appear as MULTIPLE separate issues (should be merged): {duplicated_in_output}")
        ok = False
    else:
        print("PASS: every element_ref appears as exactly one issue.")

    for ref in compounding_refs:
        matching = [i for i in report["issues"] if i["element_ref"] == ref]
        if not matching:
            print(f"FAIL: compounding element {ref} is missing from the report entirely.")
            ok = False
            continue
        agents_flagging = matching[0]["agents_flagging"]
        if len(agents_flagging) < 2:
            print(f"FAIL: compounding element {ref} should list 2+ agents_flagging, got {agents_flagging}")
            ok = False
        else:
            print(f"PASS: compounding element {ref} lists agents_flagging={agents_flagging}")

    print("\nACCEPTANCE CHECK:", "PASSED" if ok else "FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
