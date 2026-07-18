# A11yAgents Implementation Progress

This document tracks the progress of the active implementation tasks.

## Tasks

### Component 1: Project Setup and Environment
- [x] Create `implementation_tasks.md`
- [x] Add `langgraph`, `playwright`, `google-genai`, `jsonschema` to `requirements.txt`
- [x] Setup `.venv` virtual environment
- [x] Install dependencies from `requirements.txt`
- [x] Install Playwright browser binaries (Chromium)

---

### Component 2: Person 1 — Extraction Pipeline
- [x] Implement `extractor/ax_tree.py` — CDP accessibility tree parser, maps 31+ elements to `data-a11y-id`
- [x] Implement `extractor/css_snapshot.py` — contrast ratio calculation, focus ring diff checker
- [x] Implement `extractor/keyboard_sim.py` — keyboard tab traversal, focus trap detection, target size check
- [x] Implement `extractor/screenshot_crop.py` — crops element PNGs for image inspection
- [x] Implement `baseline/run_axe.py` — injects and executes Axe-core via CDN in Playwright browser
- [x] Implement `extractor/extract.py` — orchestrates extraction modules, optionally runs Axe baseline
- [x] Add `extractor/__init__.py` — proper Python package declaration
- [x] Create HTML test pages under `test_pages/` (good_page_1, broken_page_1, broken_page_2, mixed_page_1)
- [x] Generate JSON fixtures under `fixtures/`

---

### Component 3: LangGraph Restructuring
- [x] Implement `agents/agent_graph.py` — parallel `StateGraph` with `operator.add` reducer merging findings
- [x] Implement `agents/test_langgraph_agents.py` — tests for parallel execution
- [x] Add `agents/__init__.py` — proper Python package declaration
- [x] Verify LangGraph agents run correctly against fixtures

---

### Component 4: Person 4 — Orchestration, Scorer, & UI
- [x] Create `schemas/report.schema.json` — final report JSON schema definition
- [x] Create `mock_data/sample_report.json` — demo data for UI development
- [x] Implement `baseline/normalize_axe.py` — resolves Axe CSS selectors → `data-a11y-id`, maps rule IDs → WCAG criteria
- [x] Add `baseline/__init__.py` — proper Python package declaration
- [x] Implement `agents/synthesis_agent.py` — groups findings by element, severity boosting, **clean human-readable descriptions and fixes**
  - [x] `_format_description()` — strips raw Axe boilerplate, generates plain-English sentences per issue type
  - [x] `_format_fix()` — maps WCAG criteria to actionable fix instructions
  - [x] Severity compounding — multi-agent findings boosted by 1 rank
- [x] Implement `orchestrator.py` — main 4-step pipeline entry point
  - [x] Step 1: `extract_page(include_axe=True)` — single browser session does both extraction and Axe
  - [x] Step 2: `run_agent_workflow()` — fires LangGraph parallel agent graph
  - [x] Step 3: `synthesize()` — merges agent + Axe findings into unified report
  - [x] Step 4: Writes `report.json` + `report_with_axe_comparison.json`
- [x] Create `eval/ground_truth/broken_page_1.json` — ground truth issues for scoring
- [x] Implement `eval/score.py` — precision, recall, F1 scorer with partial credit + value-add metrics
- [x] Implement `eval/rubric_review.py` — CLI rubric tool to rate description clarity and actionability
- [x] Create `report_ui/index.html` — premium dark dashboard with:
  - [x] Summary severity badge cards (Critical / Serious / Moderate / Minor)
  - [x] Agent-vs-Axe comparison stacked bar chart
  - [x] Issue cards with badges (severity, WCAG criterion, agent source)
  - [x] **Filter bar** — filter issues by severity level (All / Critical / Serious / Moderate / Minor)
  - [x] **Sort dropdown** — sort by Severity / Element Ref / Agent
  - [x] **File loader** — drag-and-drop any `report.json` or `report_with_axe_comparison.json`
  - [x] Live report auto-fetch from `../report.json` when served from a local server
- [x] Update `README.md` with full execution guide
- [x] **End-to-end verification** — Pipeline ran successfully:
  - Axe-core found 3 violations → normalized → synthesized
  - Report output has clean plain-language descriptions (e.g. `"This element has a missing image alt attribute — Element does not have an alt attribute."`)
  - Fix instructions are action-oriented (e.g. `"• (WCAG 1.1.1) Add a meaningful alt attribute describing the content or purpose of the element."`)
  - `report.json` and `report_with_axe_comparison.json` written correctly
  - `eval/score.py` scored the report against ground truth (Precision 33%, Recall 25% — scores will improve significantly once GEMINI_API_KEY is set)

---

## Known Limitations / Future Work
- [ ] **Set `GEMINI_API_KEY`** — LLM agents (screen_reader, visual) return 0 findings without it. All other pipeline stages work.
- [ ] Ground truth files for `broken_page_2.html` and `mixed_page_1.html` not yet created
- [ ] `motor_agent.py` (keyboard trap/target size specialist) not yet implemented as a LangGraph node
- [ ] Report UI does not yet embed element screenshots inline on the issue cards
