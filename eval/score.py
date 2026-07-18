"""
score.py — Computes precision and recall by comparing report.json to ground truth.
Calculates value-add metrics of agents over Axe-core.
"""

from __future__ import annotations
import argparse
import json
import logging
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("a11yagents.eval.score")

def calculate_scores(report_path: Path, ground_truth_path: Path) -> dict[str, Any]:
    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)
    with open(ground_truth_path, "r", encoding="utf-8") as f:
        ground_truth = json.load(f)
        
    reported_issues = report.get("issues", [])
    
    # Track True Positives (TP), False Positives (FP), False Negatives (FN)
    # Ground truth is a list of dicts: {element_ref, wcag_criterion}
    gt_pairs = set((item["element_ref"], item["wcag_criterion"]) for item in ground_truth)
    
    tp = 0.0
    fp = 0.0
    
    matched_gt = set()
    
    for issue in reported_issues:
        ref = issue["element_ref"]
        # A reported issue can have multiple criteria, check if any match
        matched_any = False
        for criterion in issue.get("wcag_criteria", []):
            pair = (ref, criterion)
            if pair in gt_pairs:
                tp += 1.0
                matched_gt.add(pair)
                matched_any = True
            else:
                # Check for partial credit: same element, different criterion
                has_element_match = any(gt_ref == ref for gt_ref, _ in gt_pairs)
                if has_element_match:
                    tp += 0.5  # partial credit
                    # mark one element as matched to reduce FN
                    for gt_ref, gt_crit in gt_pairs:
                        if gt_ref == ref and (gt_ref, gt_crit) not in matched_gt:
                            matched_gt.add((gt_ref, gt_crit))
                            break
                    matched_any = True
                    break
        
        if not matched_any:
            fp += 1.0
            
    fn = len(gt_pairs) - len(matched_gt)
    
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    
    # Read comparison metrics
    comparison_path = report_path.parent / "report_with_axe_comparison.json"
    comp_summary = {}
    if comparison_path.exists():
        try:
            with open(comparison_path, "r", encoding="utf-8") as f:
                comp_data = json.load(f)
                comp_summary = comp_data.get("summary", {})
        except Exception:
            pass
            
    return {
        "precision": precision,
        "recall": recall,
        "f1_score": f1,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "comparison": comp_summary
    }

def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate synthesis report quality.")
    parser.add_argument("report", help="Path to report.json file.")
    parser.add_argument("--truth", help="Path to ground truth JSON file.")
    args = parser.parse_args()
    
    report_p = Path(args.report)
    
    # Fallback to local default ground truth if not supplied
    if args.truth:
        truth_p = Path(args.truth)
    else:
        truth_p = Path(__file__).resolve().parent / "ground_truth" / "broken_page_1.json"
        
    if not report_p.exists():
        logger.error("Report file not found: %s", report_p)
        return
    if not truth_p.exists():
        logger.error("Ground truth file not found: %s", truth_p)
        return
        
    scores = calculate_scores(report_p, truth_p)
    
    print("\n==========================================")
    print("           ACCESSIBILITY SCORES           ")
    print("==========================================")
    print(f"Precision:         {scores['precision']:.2%}")
    print(f"Recall:            {scores['recall']:.2%}")
    print(f"F1-Score:          {scores['f1_score']:.2%}")
    print("------------------------------------------")
    print(f"True Positives:    {scores['true_positives']:.1f}")
    print(f"False Positives:   {scores['false_positives']:.1f}")
    print(f"False Negatives:   {scores['false_negatives']:.1f}")
    print("==========================================")
    
    comp = scores.get("comparison")
    if comp:
        print("          VALUE BEYOND AXE-CORE           ")
        print("==========================================")
        print(f"Axe-core findings:  {comp.get('total_axe_findings', 0)}")
        print(f"Agent-only findings: {comp.get('agent_only_count', 0)} (Found by agents but MISSED by Axe!)")
        print(f"Overlap:            {comp.get('overlapping_count', 0)}")
        print("==========================================\n")

if __name__ == "__main__":
    main()
