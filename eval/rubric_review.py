"""
rubric_review.py — Interactive CLI tool to rate audit clarity and actionability.
Saves ratings to eval/rubric_scores.json.
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from typing import Any

def load_report(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def run_review(report_path: Path, output_path: Path) -> None:
    try:
        report = load_report(report_path)
    except FileNotFoundError:
        print(f"Report file not found: {report_path}")
        sys.exit(1)
        
    issues = report.get("issues", [])
    if not issues:
        print("No issues found in this report to review.")
        return
        
    print(f"\nLoaded {len(issues)} issues from report: {report_path.name}")
    print("Please rate each issue on a scale of 1-5 (1 = Poor, 5 = Excellent).")
    print("Press Ctrl+C to abort and save current progress.\n")
    
    ratings: list[dict[str, Any]] = []
    
    try:
        for idx, issue in enumerate(issues, 1):
            print(f"--- Issue {idx}/{len(issues)} ({issue.get('element_ref', 'N/A')}) ---")
            print(f"Severity:     {issue.get('severity', 'N/A').upper()}")
            print(f"Criteria:     {', '.join(issue.get('wcag_criteria', []))}")
            print(f"Description:  {issue.get('plain_language_description', 'N/A')}")
            print(f"Fix:          {issue.get('recommended_fix', 'N/A')}")
            print("-" * 40)
            
            # Helper to prompt safely
            def prompt_score(metric_name: str) -> int:
                while True:
                    try:
                        val = input(f"Rate {metric_name} (1-5): ").strip()
                        score = int(val)
                        if 1 <= score <= 5:
                            return score
                        print("Please enter an integer between 1 and 5.")
                    except ValueError:
                        print("Invalid input. Please enter an integer.")
                        
            clarity = prompt_score("Clarity")
            actionability = prompt_score("Actionability")
            print()
            
            ratings.append({
                "element_ref": issue.get("element_ref"),
                "severity": issue.get("severity"),
                "wcag_criteria": issue.get("wcag_criteria"),
                "clarity": clarity,
                "actionability": actionability
            })
    except KeyboardInterrupt:
        print("\nReview interrupted. Saving completed entries...")
        
    if ratings:
        # Write to JSON
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({
                "report_file": str(report_path.resolve()),
                "total_reviewed": len(ratings),
                "ratings": ratings
            }, f, indent=2)
        print(f"Rubric scores successfully saved to: {output_path}")
    else:
        print("No reviews completed. No ratings saved.")

def main() -> None:
    parser = argparse.ArgumentParser(description="CLI Rubric Review Tool")
    parser.add_argument("report", help="Path to report.json file.")
    parser.add_argument("--output", default="eval/rubric_scores.json", help="Path to save ratings.")
    args = parser.parse_args()
    
    report_p = Path(args.report)
    out_p = Path(args.output)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    
    run_review(report_p, out_p)

if __name__ == "__main__":
    main()
