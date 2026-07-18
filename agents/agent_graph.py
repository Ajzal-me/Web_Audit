"""
agent_graph.py — Orchestrates screen_reader and visual agents in parallel using LangGraph.
"""

from __future__ import annotations
import logging
import operator
import sys
from pathlib import Path
from typing import Annotated, Any, TypedDict

# pyrefly: ignore [missing-import]
from langgraph.graph import StateGraph, START, END

# Ensure parent directory and agents directory are in sys.path
_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

# Import existing agents (from same directory)
import screen_reader_agent
import visual_agent

logger = logging.getLogger("a11yagents.agents.agent_graph")
logging.basicConfig(level=logging.INFO)

# Define LangGraph State with a reducer to automatically combine findings lists
class AgentState(TypedDict):
    extraction: dict[str, Any]
    findings: Annotated[list[dict[str, Any]], operator.add]

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

# Build and compile the workflow graph
workflow = StateGraph(AgentState)

# Register nodes
workflow.add_node("screen_reader", screen_reader_node)
workflow.add_node("visual", visual_node)

# Connect start to both nodes for parallel execution
workflow.add_edge(START, "screen_reader")
workflow.add_edge(START, "visual")

# Connect both nodes to end
workflow.add_edge("screen_reader", END)
workflow.add_edge("visual", END)

compiled_graph = workflow.compile()

def run_agent_workflow(extraction_data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Entry point to run the compiled LangGraph workflow.
    Takes extraction dictionary and returns list of merged findings.
    """
    initial_state = {
        "extraction": extraction_data,
        "findings": []
    }
    logger.info("Invoking LangGraph compiled workflow...")
    result = compiled_graph.invoke(initial_state)
    return result.get("findings", [])
