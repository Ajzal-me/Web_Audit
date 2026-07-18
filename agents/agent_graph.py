"""
agent_graph.py — Orchestrates all four inspection agents (screen_reader, visual,
motor, axe_baseline) in parallel using LangGraph, then runs synthesis_agent as a
join step once every branch has finished.

Graph shape:
    START -> screen_reader, visual, motor, axe_baseline  (all run in parallel)
    screen_reader, visual, motor, axe_baseline -> synthesize  (fan-in / join —
        LangGraph only runs "synthesize" once ALL four predecessors have
        completed for that step)
    synthesize -> END
"""

from __future__ import annotations
import json
import logging
import operator
import sys
from pathlib import Path
from typing import Annotated, Any, Optional, TypedDict

from langgraph.graph import StateGraph, START, END

# Ensure parent directory is in sys.path
_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_ROOT / "baseline") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "baseline"))

# Import existing agents (from same directory)
import screen_reader_agent
import visual_agent
import motor_agent
import synthesis_agent
from normalize_axe import normalize_violations

logger = logging.getLogger("a11yagents.agents.agent_graph")
logging.basicConfig(level=logging.INFO)

_DEFAULT_MOCK_AXE_VIOLATIONS = _REPO_ROOT / "fixtures" / "mock_axe_violations.json"
_DEFAULT_MOCK_AXE_MAPPING = _REPO_ROOT / "fixtures" / "mock_axe_selector_to_ref.json"


# Define LangGraph State with a reducer to automatically combine findings lists
class AgentState(TypedDict):
    extraction: dict[str, Any]
    findings: Annotated[list[dict[str, Any]], operator.add]
    # Optional real axe-core inputs. If not supplied by the caller (e.g. before
    # Person 1's live-page axe resolution is wired in), axe_baseline_node falls
    # back to the hand-written mock fixtures so the graph is always runnable.
    axe_violations: Optional[list[dict[str, Any]]]
    axe_selector_to_ref: Optional[dict[str, str]]
    # Filled in by the synthesize node once all four branches have joined.
    report: Optional[dict[str, Any]]

def screen_reader_node(state: AgentState) -> dict[str, Any]:
    """Runs the screen reader agent on the extracted page data."""
    logger.info("Executing screen_reader_node...")
    try:
        findings = screen_reader_agent.run(state["extraction"])
        logger.info("screen_reader_node found %d issues", len(findings))
        return {"findings": findings}
    except Exception as e:
        logger.error("Error in screen_reader_node: %s", e)
        return {"findings": []}

def visual_node(state: AgentState) -> dict[str, Any]:
    """Runs the visual agent on the extracted page data."""
    logger.info("Executing visual_node...")
    try:
        findings = visual_agent.run(state["extraction"])
        logger.info("visual_node found %d issues", len(findings))
        return {"findings": findings}
    except Exception as e:
        logger.error("Error in visual_node: %s", e)
        return {"findings": []}

def motor_node(state: AgentState) -> dict[str, Any]:
    """Runs the motor agent (keyboard/target-size checks) on the extracted page data."""
    logger.info("Executing motor_node...")
    try:
        findings = motor_agent.run(state["extraction"])
        logger.info("motor_node found %d issues", len(findings))
        return {"findings": findings}
    except Exception as e:
        logger.error("Error in motor_node: %s", e)
        return {"findings": []}

def axe_baseline_node(state: AgentState) -> dict[str, Any]:
    """Normalizes raw axe-core violations into finding.schema.json shape.

    Uses state["axe_violations"] / state["axe_selector_to_ref"] if the caller
    supplied them (real data, once Person 1's live-page axe resolution is
    wired in). Falls back to the hand-written mock fixtures otherwise, so this
    node — and the whole graph — is runnable without a live browser."""
    logger.info("Executing axe_baseline_node...")
    try:
        violations = state.get("axe_violations")
        selector_to_ref = state.get("axe_selector_to_ref")
        if violations is None or selector_to_ref is None:
            logger.info(
                "axe_baseline_node: no real axe data supplied, falling back to mock fixtures "
                "(%s, %s)",
                _DEFAULT_MOCK_AXE_VIOLATIONS,
                _DEFAULT_MOCK_AXE_MAPPING,
            )
            violations = json.loads(_DEFAULT_MOCK_AXE_VIOLATIONS.read_text(encoding="utf-8"))
            selector_to_ref = json.loads(_DEFAULT_MOCK_AXE_MAPPING.read_text(encoding="utf-8"))
        findings = normalize_violations(violations, selector_to_ref)
        logger.info("axe_baseline_node found %d issues", len(findings))
        return {"findings": findings}
    except Exception as e:
        logger.error("Error in axe_baseline_node: %s", e)
        return {"findings": []}

def synthesize_node(state: AgentState) -> dict[str, Any]:
    """Join step: runs only once screen_reader, visual, motor, and
    axe_baseline have all completed (LangGraph waits for every incoming edge
    before running a fan-in node). Merges all accumulated findings into a
    final report via synthesis_agent."""
    logger.info("Executing synthesize_node with %d total findings...", len(state["findings"]))
    try:
        report = synthesis_agent.run(state["findings"], page=state["extraction"].get("page", ""))
        if report is None:
            logger.error("synthesize_node: synthesis_agent.run() returned None (schema validation failed)")
            return {"report": None}
        logger.info("synthesize_node produced a report with %d issue(s)", len(report["issues"]))
        return {"report": report}
    except Exception as e:
        logger.error("Error in synthesize_node: %s", e)
        return {"report": None}

# Build and compile the workflow graph
workflow = StateGraph(AgentState)

# Register nodes
workflow.add_node("screen_reader", screen_reader_node)
workflow.add_node("visual", visual_node)
workflow.add_node("motor", motor_node)
workflow.add_node("axe_baseline", axe_baseline_node)
workflow.add_node("synthesize", synthesize_node)

# Connect start to all four inspection nodes for parallel execution
workflow.add_edge(START, "screen_reader")
workflow.add_edge(START, "visual")
workflow.add_edge(START, "motor")
workflow.add_edge(START, "axe_baseline")

# Fan-in: synthesize only runs once ALL FOUR have completed
workflow.add_edge("screen_reader", "synthesize")
workflow.add_edge("visual", "synthesize")
workflow.add_edge("motor", "synthesize")
workflow.add_edge("axe_baseline", "synthesize")

workflow.add_edge("synthesize", END)

compiled_graph = workflow.compile()

def run_agent_workflow(extraction_data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Entry point to run the compiled LangGraph workflow.
    Takes extraction dictionary and returns list of merged findings from all
    four agents (screen_reader, visual, motor, axe_baseline).

    Kept for backward compatibility with existing callers (e.g.
    test_langgraph_agents.py) that only want the raw findings list, not the
    synthesized report. Use run_full_pipeline() to get the report too.
    """
    initial_state: AgentState = {
        "extraction": extraction_data,
        "findings": [],
        "axe_violations": None,
        "axe_selector_to_ref": None,
        "report": None,
    }
    logger.info("Invoking LangGraph compiled workflow...")
    result = compiled_graph.invoke(initial_state)
    return result.get("findings", [])

def run_full_pipeline(
    extraction_data: dict[str, Any],
    axe_violations: Optional[list[dict[str, Any]]] = None,
    axe_selector_to_ref: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """
    Entry point that returns BOTH the raw findings list and the final
    synthesized report: {"findings": [...], "report": {...} | None}.

    Pass real axe_violations/axe_selector_to_ref once Person 1's live-page
    axe resolution exists; omit them to use the mock fixtures automatically.
    """
    initial_state: AgentState = {
        "extraction": extraction_data,
        "findings": [],
        "axe_violations": axe_violations,
        "axe_selector_to_ref": axe_selector_to_ref,
        "report": None,
    }
    logger.info("Invoking full LangGraph pipeline (4 agents + synthesis)...")
    result = compiled_graph.invoke(initial_state)
    return {"findings": result.get("findings", []), "report": result.get("report")}
