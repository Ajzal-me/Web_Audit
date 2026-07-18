# A11yAgents — Multi-Agent Web Accessibility Audit Pipeline

A state-of-the-art accessibility auditor that combines Playwright browser simulation, Axe-core automated scanning, and parallel LLM agents orchestrated via LangGraph to perform deep compliance reviews against WCAG 2.2 criteria.

---

## Repository Structure

```
Web_Audit/
├── schemas/                    # JSON Schemas for data models
│   ├── extraction.schema.json  # Output shape of the Playwright extractor
│   ├── finding.schema.json     # Standardized format of audit findings
│   └── report.schema.json      # Shape of the final merged synthesis report
├── test_pages/                 # HTML test pages with varying accessibility bugs
│   ├── good_page_1.html        # Fully accessible reference page
│   ├── broken_page_1.html      # Screen reader violations
│   ├── broken_page_2.html      # Motor & visual violations
│   └── mixed_page_1.html       # Mix of multiple violations
├── fixtures/                   # Generated extractor output files for test pages
├── extractor/                  # Playwright page extraction pipeline
│   ├── extract.py              # Main extraction orchestrator
│   ├── ax_tree.py              # CDP accessibility tree parser
│   ├── css_snapshot.py         # Color contrast & focus indicator styles check
│   ├── keyboard_sim.py         # Keyboard tab navigation, traps, target sizes
│   └── screenshot_crop.py      # Element screenshot cropping
├── baseline/                   # Axe-core baseline testing
│   ├── run_axe.py              # Injects and executes Axe-core in browser
│   └── normalize_axe.py        # Normalizes raw Axe violations to standard findings
├── agents/                     # LLM auditing agents
│   ├── base_agent.py           # Shared utilities & Gemini API wrapper
│   ├── screen_reader_agent.py  # Screen reader alt-text & hierarchy audit
│   ├── visual_agent.py         # Contrast & reflow layout audit
│   ├── synthesis_agent.py      # Combines, merges, and summarizes findings
│   └── agent_graph.py          # Parallel orchestration graph built in LangGraph
├── eval/                       # Scoring and evaluation harness
│   ├── ground_truth/           # Ground truth files containing known page bugs
│   ├── score.py                # Computes Precision & Recall scores
│   └── rubric_review.py        # Interactive CLI review for description clarity
├── report_ui/                  # HTML Dashboard
│   └── index.html              # Premium dark-themed visual report viewer
├── orchestrator.py             # Main entry point to run the entire pipeline
└── README.md
```

---

## Getting Started

### 1. Setup Environment
Initialize the local virtual environment and install all packages:

```bash
# Create virtual environment
python -m venv .venv

# Install requirements (google-genai, jsonschema, langgraph, playwright)
.venv\Scripts\pip install -r requirements.txt

# Install Playwright browser binaries
.venv\Scripts\playwright install chromium
```

### 2. Configure Gemini API Key
The Screen Reader and Visual agents call the Gemini API via the `google-genai` SDK. Set your key:

```powershell
# PowerShell
$env:GEMINI_API_KEY="your_google_ai_studio_api_key"

# Command Prompt (cmd)
set GEMINI_API_KEY=your_google_ai_studio_api_key
```

*Note: If no API key is present or it is invalid, the orchestrator will catch the error and execute gracefully, returning 0 findings for the LLM nodes while still writing standard Axe and keyboard simulation reports.*

---

## Execution Guide

### 1. Run the Orchestrator Pipeline
To audit any web page or local HTML file and compile the final reports:

```bash
# Run end-to-end audit
.venv\Scripts\python orchestrator.py test_pages/broken_page_1.html --output report.json
```

This compiles:
- `report.json`: The final merged, categorized accessibility report.
- `report_with_axe_comparison.json`: A comparison layout partitioning Agent-only, Axe-only, and Overlapping violations.

---

## Verification & Evaluation

### 1. Run Evaluation Scorer
To measure Precision, Recall, and F1-Score compared to ground truth:

```bash
.venv\Scripts\python eval/score.py report.json
```

This prints statistical scores alongside the **Value Beyond Axe-core** (Agent-only vs Axe-only vs Overlapping) headline metrics.

### 2. CLI Rubric Review
To rate the clarity and actionability of descriptions and recommended fixes:

```bash
.venv\Scripts\python eval/rubric_review.py report.json
```

Ratings are saved locally to `eval/rubric_scores.json`.

### 3. Open HTML Visual Dashboard
Simply open the visual dashboard in any browser:

```bash
# On Windows
start report_ui/index.html
```

- **Custom Report Loading**: Drag and drop or click the **Load Custom Report** button at the top right to upload your generated `report.json` or `report_with_axe_comparison.json` file. It will parse and render your findings immediately!
- The dashboard spotlights **summary indicators**, **value-add comparison metrics**, and **detailed recommendations**.