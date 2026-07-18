"""
<<<<<<< HEAD
synthesis_agent.py — Groups findings by element and compiles the final report.
Provides a deterministic Python-based merge algorithm as a baseline.
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("a11yagents.agents.synthesis_agent")

SEVERITY_RANKS = {"critical": 3, "serious": 2, "moderate": 1, "minor": 0}
RANK_TO_SEVERITY = {3: "critical", 2: "serious", 1: "moderate", 0: "minor"}

# Maps raw issue_type tokens (from agents or axe rule IDs) to human-readable phrases
ISSUE_TYPE_LABELS: dict[str, str] = {
    "missing_alt": "missing or empty alt text",
    "meaningless_alt": "a meaningless filename used as alt text",
    "unlabeled_control": "an unlabeled interactive control",
    "meaningless_link_text": "meaningless link text (e.g. 'click here')",
    "heading_structure": "a broken heading hierarchy",
    "low_contrast": "insufficient color contrast",
    "no_focus_ring": "no visible keyboard focus indicator",
    "small_target": "a touch/click target that is too small",
    "keyboard_trap": "a keyboard focus trap",
    # Axe-core rule IDs (underscored)
    "image_alt": "a missing image alt attribute",
    "button_name": "an unlabeled button with no accessible name",
    "link_name": "a link with no accessible name",
    "label": "a form input with no associated label",
    "color_contrast": "insufficient color contrast ratio",
    "heading_order": "headings that skip levels (e.g. h1 → h3 with no h2)",
    "aria_input_field_name": "an ARIA input field with no accessible name",
    "frame_title": "an iframe with no title attribute",
}

# Maps WCAG criterion IDs to short, action-oriented fix instructions
WCAG_PLAIN: dict[str, str] = {
    "1.1.1": "add a meaningful alt attribute describing the content or purpose of the element",
    "1.3.1": "use semantic HTML elements and ARIA roles so structure is conveyed programmatically",
    "1.4.3": "increase the contrast ratio between text and background to at least 4.5:1",
    "1.4.11": "ensure non-text UI components have at least 3:1 contrast against adjacent colors",
    "2.1.1": "ensure all functionality can be accessed and operated using only a keyboard",
    "2.1.2": "ensure users can move keyboard focus away from this element using the Tab or Escape key",
    "2.4.3": "ensure focusable elements receive focus in a logical order that matches visual layout",
    "2.4.4": "replace vague link text with a description of the link destination or purpose",
    "2.4.7": "add a visible :focus style (outline, border, or background change) to this element",
    "2.5.8": "increase the padding or size of this element's click/touch target to at least 24×24 CSS pixels",
    "4.1.2": "add a visible <label>, aria-label, or aria-labelledby so assistive technologies can read its name",
}


def _clean_evidence(raw: str) -> str:
    """Strip verbose Axe boilerplate ('Fix any of the following:...') from evidence strings."""
    if not raw:
        return ""
    if "Fix any of the following" in raw:
        lines = [
            line.strip()
            for line in raw.split("\n")
            if line.strip() and not line.strip().startswith("Fix any")
        ]
        return lines[0] if lines else ""
    return raw


def _format_description(group: list[dict]) -> str:
    """Produce a clean, plain-English description from a group of findings on the same element."""
    sentences: list[str] = []
    seen: set[tuple[str, str]] = set()

    for f in group:
        issue_type = f.get("issue_type", "")
        label = ISSUE_TYPE_LABELS.get(issue_type, issue_type.replace("_", " "))
        core = _clean_evidence(f.get("evidence", ""))

        dedup_key = (issue_type, core[:60])
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        if core:
            sentences.append(f"This element has {label} — {core}.")
        else:
            agent = f.get("agent", "auditor").replace("_", " ").replace("axe baseline", "the automated scan")
            sentences.append(f"This element has {label}, flagged by {agent}.")

    return " ".join(sentences)


def _format_fix(group: list[dict]) -> str:
    """Produce concise, actionable fix instructions based on WCAG criteria violated."""
    fixes: list[str] = []
    seen_criteria: set[str] = set()

    for f in group:
        criterion = f.get("wcag_criterion", "")
        if criterion in seen_criteria:
            continue
        seen_criteria.add(criterion)
        instruction = WCAG_PLAIN.get(criterion, f"comply with WCAG {criterion}")
        fixes.append(f"• (WCAG {criterion}) {instruction.capitalize()}.")

    return " ".join(fixes)


def synthesize(page: str, findings: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Groups findings by element_ref and compiles a final report.
    Returns a dict matching schemas/report.schema.json.

    Algorithm:
      1. Group all findings by element_ref.
      2. For each group, take the maximum severity.
      3. If multiple distinct agents flagged the same element, boost severity by 1 rank.
      4. Format clean plain-language descriptions and fix instructions.
      5. Sort issues by final severity, descending.
    """
    logger.info("Starting synthesis for page: %s with %d total findings", page, len(findings))

    # 1. Group by element_ref
    by_element: dict[str, list[dict[str, Any]]] = {}
    for f in findings:
        ref = f.get("element_ref", "unknown")
        by_element.setdefault(ref, []).append(f)

    issues: list[dict[str, Any]] = []
    summary = {"critical": 0, "serious": 0, "moderate": 0, "minor": 0}

    # 2. Process each element group
    for ref, group in by_element.items():
        criteria = sorted(set(f["wcag_criterion"] for f in group))
        agents = sorted(set(f["agent"] for f in group))

        # Take the highest severity reported for this element
        max_rank = max(SEVERITY_RANKS.get(f.get("severity", "minor"), 0) for f in group)

        # Compound issue logic: multiple distinct agents → bump severity by 1
        if len(agents) > 1 and max_rank < 3:
            max_rank += 1
            logger.info(
                "Compounding issue for element %s: boosting to %s (flagged by: %s)",
                ref, RANK_TO_SEVERITY[max_rank], ", ".join(agents)
            )

        final_severity = RANK_TO_SEVERITY[max_rank]
        summary[final_severity] += 1

        evidence = [_clean_evidence(f.get("evidence", "")) for f in group]

        issues.append({
            "element_ref": ref,
            "wcag_criteria": criteria,
            "severity": final_severity,
            "agents_flagging": agents,
            "plain_language_description": _format_description(group),
            "recommended_fix": _format_fix(group),
            "evidence": [e for e in evidence if e],  # strip empty strings
        })

    # 3. Sort issues by severity descending (critical first)
    issues.sort(key=lambda x: SEVERITY_RANKS.get(x["severity"], 0), reverse=True)

    return {
        "page": page,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": summary,
        "issues": issues,
    }
=======
synthesis_agent.py — Person 3's merge/synthesis agent.

Input: a flat list of findings (finding.schema.json-shaped), from all agents
combined (real, at integration time; mock_data/sample_findings.json while
developing solo).

Step A (deterministic Python, NOT the LLM): group findings by element_ref.
Where 2+ agents flagged the same element, that's kept explicit as a single
compounding issue rather than being dropped to one arbitrary finding or
silently deduplicated away.

Step B (LLM call, one per group, batched): assign final severity (a
compounding issue should generally not rank below the severity of any single
contributing finding — this is stated to the model as an instruction, not
computed in code, since "should generally" allows for judgment calls), write
ONE plain-language description and ONE recommended fix per group (not one per
raw finding, to avoid repeating near-identical advice for the same element).

Step C (LLM call): order the full issue list by priority (index 0 = fix
first).

Output must validate against schemas/report.schema.json.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from base_agent import call_llm, load_wcag_criteria, validate_report

logger = logging.getLogger("a11yagents.synthesis_agent")

GROUP_BATCH_SIZE = 8
_SEVERITY_RANK = {"critical": 0, "serious": 1, "moderate": 2, "minor": 3}

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent


def _wcag_list_str() -> str:
    criteria = load_wcag_criteria()
    lines = [f"- {cid}: {c['title']} — {c['short_description']}" for cid, c in criteria.items()]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Step A — deterministic grouping (no LLM)
# ---------------------------------------------------------------------------

def _group_by_element_ref(findings: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in findings:
        groups[f["element_ref"]].append(f)
    return dict(groups)


def _worst_severity(findings: list[dict[str, Any]]) -> str:
    return min((f["severity"] for f in findings), key=lambda s: _SEVERITY_RANK.get(s, 3))


# ---------------------------------------------------------------------------
# Step B — LLM: severity + description + fix, per group
# ---------------------------------------------------------------------------

GROUP_SYSTEM_PROMPT = """You are an accessibility auditor writing the final, user-facing \
version of a set of already-confirmed findings for a report. You will be given several \
GROUPS. Each group is all the findings for ONE element on the page (element_ref is fixed \
per group) — sometimes from just one detection agent, sometimes from two or more agents \
independently flagging the same element (a "compounding" issue, which is normally worse \
than any single one of them, not better).

For each group, produce exactly ONE merged issue:
- final_severity: "critical" | "serious" | "moderate" | "minor". A compounding issue \
(2+ distinct agents in the group) should generally not rank below the severity of any \
individual finding in that group — often it should rank at or above the worst individual \
severity, since multiple independent detection methods agreeing is itself a signal of \
real impact. Use judgment; this is a guideline, not a hard floor you must mechanically \
apply in every case.
- plain_language_description: ONE description in plain, non-technical language covering \
the whole group — do not write one sentence per raw finding, and do not just concatenate \
the evidence strings. If it's a compounding issue, the description should reflect that \
multiple things are wrong with this one element, not just restate one of them.
- recommended_fix: ONE concrete, actionable fix for the whole group. If the group's \
findings suggest genuinely different fixes, prioritize the fix that would resolve the \
most severe underlying problem, but keep it to one recommendation, not a list.
- wcag_criteria: the deduplicated list of every distinct WCAG criterion cited across the \
group's findings (there may be more than one for a compounding issue).

You MUST only use wcag_criterion values from this fixed list:
{wcag_list}

Respond with ONLY a JSON array (no markdown fences, no preamble), one object per group, \
in the SAME ORDER the groups were given to you, each with exactly these fields:
  group_index: the integer index of the group as given to you (so we can match your \
output back to the right group)
  final_severity: your judgment
  plain_language_description: as described above
  recommended_fix: as described above
  wcag_criteria: array of strings, deduplicated
"""


def _build_group_payload(element_ref: str, findings: list[dict[str, Any]], group_index: int) -> dict:
    return {
        "group_index": group_index,
        "element_ref": element_ref,
        "agents_flagging": sorted({f["agent"] for f in findings}),
        "findings": [
            {
                "agent": f["agent"],
                "issue_type": f["issue_type"],
                "wcag_criterion": f["wcag_criterion"],
                "severity": f["severity"],
                "evidence": f["evidence"],
            }
            for f in findings
        ],
    }


def _synthesize_groups(
    grouped: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    """Returns a list of partially-built issue dicts (missing issue_id and
    priority_rank, which are filled in later) — one per element_ref group."""
    element_refs = list(grouped.keys())
    wcag_list = _wcag_list_str()
    system_prompt = GROUP_SYSTEM_PROMPT.format(wcag_list=wcag_list)

    issues: dict[int, dict[str, Any]] = {}

    for batch_start in range(0, len(element_refs), GROUP_BATCH_SIZE):
        batch_refs = element_refs[batch_start : batch_start + GROUP_BATCH_SIZE]
        payloads = [
            _build_group_payload(ref, grouped[ref], batch_start + i)
            for i, ref in enumerate(batch_refs)
        ]
        user_content = "Groups:\n" + json.dumps(payloads, indent=2)

        try:
            raw = call_llm(system_prompt, user_content, max_tokens=3000)
        except Exception as e:  # noqa: BLE001
            logger.error("synthesis_agent: group batch call failed, falling back to deterministic merge for this batch: %s", e)
            for i, ref in enumerate(batch_refs):
                issues[batch_start + i] = _fallback_merge(ref, grouped[ref], batch_start + i)
            continue

        try:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                lines = cleaned.splitlines()
                if lines and lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip().startswith("```"):
                    lines = lines[:-1]
                cleaned = "\n".join(lines)
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error("synthesis_agent: could not parse group batch response, falling back to deterministic merge: %s", e)
            for i, ref in enumerate(batch_refs):
                issues[batch_start + i] = _fallback_merge(ref, grouped[ref], batch_start + i)
            continue

        returned_indices = set()
        for item in parsed:
            idx = item.get("group_index")
            if idx is None or idx not in {batch_start + i for i in range(len(batch_refs))}:
                logger.warning("synthesis_agent: dropping group result with unexpected group_index %r", idx)
                continue
            ref = element_refs[idx]
            group_findings = grouped[ref]
            issues[idx] = {
                "issue_id": str(uuid.uuid4()),
                "element_ref": ref,
                "agents_flagging": sorted({f["agent"] for f in group_findings}),
                "wcag_criteria": sorted(set(item.get("wcag_criteria") or [f["wcag_criterion"] for f in group_findings])),
                "severity": item.get("final_severity") or _worst_severity(group_findings),
                "plain_language_description": item.get("plain_language_description", ""),
                "recommended_fix": item.get("recommended_fix", ""),
                "source_findings": [f["finding_id"] for f in group_findings],
            }
            returned_indices.add(idx)

        # Anything the model skipped in this batch still needs an issue.
        for i, ref in enumerate(batch_refs):
            idx = batch_start + i
            if idx not in returned_indices:
                logger.warning("synthesis_agent: model omitted group_index %d, using deterministic fallback", idx)
                issues[idx] = _fallback_merge(ref, grouped[ref], idx)

    return [issues[i] for i in sorted(issues.keys())]


def _fallback_merge(element_ref: str, findings: list[dict[str, Any]], group_index: int) -> dict[str, Any]:
    """Deterministic, no-LLM merge used only if the LLM call/parse fails for a
    batch, so synthesis never crashes or drops a group entirely."""
    return {
        "issue_id": str(uuid.uuid4()),
        "element_ref": element_ref,
        "agents_flagging": sorted({f["agent"] for f in findings}),
        "wcag_criteria": sorted({f["wcag_criterion"] for f in findings}),
        "severity": _worst_severity(findings),
        "plain_language_description": "; ".join(f["evidence"] for f in findings),
        "recommended_fix": "Review this element against the WCAG criteria listed above.",
        "source_findings": [f["finding_id"] for f in findings],
    }


# ---------------------------------------------------------------------------
# Step C — LLM: priority ordering of the full issue list
# ---------------------------------------------------------------------------

ORDER_SYSTEM_PROMPT = """You are prioritizing a finished list of accessibility issues for \
a report. You will be given each issue's id, severity, which agents flagged it (more \
agents = more independently-confirmed = generally higher priority), and its \
plain-language description. Order them by priority: what should a developer fix first?

Generally: critical > serious > moderate > minor, and within the same severity, an issue \
flagged by more agents should rank higher, and an issue on what sounds like core/primary \
functionality (e.g. checkout, primary navigation, login) should rank above an issue on \
something incidental — but use holistic judgment rather than mechanically sorting by \
these alone.

Respond with ONLY a JSON array (no markdown fences, no preamble) of issue_id strings in \
priority order — the same set of ids you were given, each exactly once, most urgent \
first.
"""


def _order_by_priority(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not issues:
        return []

    payload = [
        {
            "issue_id": issue["issue_id"],
            "severity": issue["severity"],
            "agents_flagging": issue["agents_flagging"],
            "plain_language_description": issue["plain_language_description"],
        }
        for issue in issues
    ]
    user_content = "Issues:\n" + json.dumps(payload, indent=2)

    order: Optional[list[str]] = None
    try:
        raw = call_llm(ORDER_SYSTEM_PROMPT, user_content, max_tokens=2000)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines)
        parsed = json.loads(cleaned)
        if isinstance(parsed, list) and set(parsed) == {i["issue_id"] for i in issues}:
            order = parsed
        else:
            logger.warning("synthesis_agent: priority ordering response didn't match the issue-id set exactly, falling back to deterministic sort")
    except Exception as e:  # noqa: BLE001
        logger.error("synthesis_agent: priority ordering call failed, falling back to deterministic sort: %s", e)

    if order is None:
        # Deterministic fallback: severity rank, then more agents_flagging first.
        issues_sorted = sorted(
            issues,
            key=lambda i: (_SEVERITY_RANK.get(i["severity"], 3), -len(i["agents_flagging"])),
        )
    else:
        by_id = {i["issue_id"]: i for i in issues}
        issues_sorted = [by_id[iid] for iid in order]

    for rank, issue in enumerate(issues_sorted, start=1):
        issue["priority_rank"] = rank

    return issues_sorted


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(findings: list[dict[str, Any]], page: str = "") -> Optional[dict[str, Any]]:
    """Takes a flat list of finding.schema.json-shaped dicts, returns a
    report.schema.json-validated dict, or None if the final report somehow
    fails schema validation (logged; caller should not write a report.json
    in that case)."""
    if not findings:
        report = {
            "page": page,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "issues": [],
            "summary": {"total_issues": 0, "by_severity": {"critical": 0, "serious": 0, "moderate": 0, "minor": 0}},
        }
        return validate_report(report)

    grouped = _group_by_element_ref(findings)
    issues = _synthesize_groups(grouped)
    issues = _order_by_priority(issues)

    by_severity = {"critical": 0, "serious": 0, "moderate": 0, "minor": 0}
    for issue in issues:
        by_severity[issue["severity"]] = by_severity.get(issue["severity"], 0) + 1

    report = {
        "page": page,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {"total_issues": len(issues), "by_severity": by_severity},
        "issues": issues,
    }

    return validate_report(report)


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else str(_REPO_ROOT / "mock_data" / "sample_findings.json")
    with open(path, "r", encoding="utf-8") as f:
        findings_data = json.load(f)

    result = run(findings_data, page="mock_data/sample_findings.json")
    if result is None:
        print("Synthesis FAILED schema validation — see log output above.")
        sys.exit(1)
    print(json.dumps(result, indent=2))
>>>>>>> 0835fb10269ca5c48eb5e12bd3a96ad7762cbc16
