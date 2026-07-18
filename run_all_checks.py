"""
run_all_checks.py — single entry point to sanity-check Person 1, 2, and 3's
work together. Run this from the repo root:

    python run_all_checks.py

Steps that need NO API key (structural/offline checks, run first so you get
signal even without GEMINI_API_KEY set):
    1. Validate every fixtures/extraction_*.json against schemas/extraction.schema.json
       (Person 1's contract compliance)
    2. Validate baseline/normalize_axe.py's output against schemas/finding.schema.json
       using the mock axe fixtures (Person 3, axe half)

Steps that DO need GEMINI_API_KEY set (real LLM calls):
    3. Run the full LangGraph pipeline (screen_reader + visual + motor +
       axe_baseline -> synthesize) against fixtures/extraction_broken_page_1.json
       and confirm a schema-valid report comes out (Person 2 + Person 3, full loop)
    4. Run synthesis_agent against mock_data/sample_findings.json and check the
       compounding-issue acceptance criterion from the plan (Person 3, synthesis half)

Exits with code 0 if everything passes, 1 if anything fails, printing a clear
summary either way.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_REPO_ROOT / "agents"))
sys.path.insert(0, str(_REPO_ROOT / "baseline"))

results: dict[str, bool] = {}


def _header(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


# ---------------------------------------------------------------------------
# 1. Fixture <-> extraction schema validation (Person 1, no API key)
# ---------------------------------------------------------------------------

def check_fixtures_valid() -> bool:
    _header("1. Validating fixtures against schemas/extraction.schema.json (Person 1)")
    import jsonschema

    schema = json.loads((_REPO_ROOT / "schemas" / "extraction.schema.json").read_text())
    fixtures_dir = _REPO_ROOT / "fixtures"
    extraction_fixtures = sorted(fixtures_dir.glob("extraction_*.json"))

    if not extraction_fixtures:
        print("FAIL: no fixtures/extraction_*.json files found at all.")
        return False

    ok = True
    for fp in extraction_fixtures:
        try:
            data = json.loads(fp.read_text())
            jsonschema.validate(instance=data, schema=schema)
            print(f"  PASS: {fp.name}")
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL: {fp.name} -> {e}")
            ok = False
    return ok


# ---------------------------------------------------------------------------
# 2. normalize_axe output <-> finding schema (Person 3, no API key)
# ---------------------------------------------------------------------------

def check_normalize_axe() -> bool:
    _header("2. Checking baseline/normalize_axe.py against mock axe fixtures (Person 3, no API key)")
    import jsonschema
    from normalize_axe import normalize_violations

    violations_path = _REPO_ROOT / "fixtures" / "mock_axe_violations.json"
    mapping_path = _REPO_ROOT / "fixtures" / "mock_axe_selector_to_ref.json"
    if not violations_path.exists() or not mapping_path.exists():
        print(f"FAIL: missing {violations_path.name} or {mapping_path.name}")
        return False

    violations = json.loads(violations_path.read_text())
    mapping = json.loads(mapping_path.read_text())
    findings = normalize_violations(violations, mapping)

    if not findings:
        print("FAIL: normalize_violations() returned zero findings from a non-empty mock fixture.")
        return False

    schema = json.loads((_REPO_ROOT / "schemas" / "finding.schema.json").read_text())
    ok = True
    for f in findings:
        try:
            jsonschema.validate(instance=f, schema=schema)
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL: normalized finding failed schema validation -> {e}")
            ok = False
    if ok:
        print(f"  PASS: all {len(findings)} normalized axe findings are schema-valid.")
    return ok


# ---------------------------------------------------------------------------
# 3. Full LangGraph pipeline (Person 2 + Person 3, needs API key)
# ---------------------------------------------------------------------------

def check_full_pipeline() -> bool:
    _header("3. Running full LangGraph pipeline: screen_reader + visual + motor + "
            "axe_baseline -> synthesize (Person 2 + 3, needs GEMINI_API_KEY)")
    from agent_graph import run_full_pipeline

    fixture_path = _REPO_ROOT / "fixtures" / "extraction_broken_page_1.json"
    extraction = json.loads(fixture_path.read_text())

    result = run_full_pipeline(extraction)
    findings = result["findings"]
    report = result["report"]

    print(f"  {len(findings)} raw finding(s) from agents: "
          f"{sorted({f['agent'] for f in findings}) if findings else '(none)'}")

    if report is None:
        print("  FAIL: synthesis produced no report (schema validation or synthesis error — see logs above).")
        return False

    print(f"  PASS: synthesized report has {len(report['issues'])} issue(s), "
          f"summary={report.get('summary')}")
    return True


# ---------------------------------------------------------------------------
# 4. Synthesis acceptance check (Person 3, needs API key)
# ---------------------------------------------------------------------------

def check_synthesis_acceptance() -> bool:
    _header("4. Synthesis acceptance check against mock_data/sample_findings.json "
            "(Person 3, needs GEMINI_API_KEY)")
    import synthesis_agent

    findings_path = _REPO_ROOT / "mock_data" / "sample_findings.json"
    findings = json.loads(findings_path.read_text())

    input_ref_counts = Counter(f["element_ref"] for f in findings)
    compounding_refs = {ref for ref, count in input_ref_counts.items() if count > 1}

    report = synthesis_agent.run(findings, page=str(findings_path))
    if report is None:
        print("  FAIL: synthesis_agent.run() returned None.")
        return False

    output_refs = [issue["element_ref"] for issue in report["issues"]]
    output_ref_counts = Counter(output_refs)
    duplicated = {ref for ref, count in output_ref_counts.items() if count > 1}

    ok = True
    if duplicated:
        print(f"  FAIL: element_refs appearing as multiple separate issues: {duplicated}")
        ok = False
    else:
        print("  PASS: every element_ref appears as exactly one issue.")

    for ref in compounding_refs:
        matching = [i for i in report["issues"] if i["element_ref"] == ref]
        if not matching or len(matching[0]["agents_flagging"]) < 2:
            print(f"  FAIL: compounding element {ref} not correctly merged.")
            ok = False
    if ok:
        print(f"  PASS: all {len(compounding_refs)} compounding element(s) correctly show 2+ agents_flagging.")

    return ok


def main() -> None:
    has_key = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))

    results["fixtures_valid (Person 1)"] = check_fixtures_valid()
    results["normalize_axe (Person 3, no key)"] = check_normalize_axe()

    if has_key:
        results["full_pipeline (Person 2+3)"] = check_full_pipeline()
        results["synthesis_acceptance (Person 3)"] = check_synthesis_acceptance()
    else:
        print("\n" + "=" * 70)
        print("NOTE: GEMINI_API_KEY / GOOGLE_API_KEY not set — skipping the two checks "
              "that make real LLM calls (full pipeline + synthesis acceptance).\n"
              "Set your key and re-run to check those too:\n"
              "    export GEMINI_API_KEY=your-key-here")
        print("=" * 70)

    _header("SUMMARY")
    all_ok = True
    for name, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'} — {name}")
        all_ok = all_ok and ok

    if not has_key:
        print("  SKIPPED — full_pipeline (Person 2+3)  [no API key]")
        print("  SKIPPED — synthesis_acceptance (Person 3)  [no API key]")

    print()
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
