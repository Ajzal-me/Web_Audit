# A11yAgents — Parallel 4-Person Implementation Plan

## Why this needs restructuring from a 4-part sequential plan

The earlier 4-part plan is a dependency chain: agents need extraction output, synthesis needs
agent output, evaluation needs everything. If 4 people each take one "part," three of them sit
idle waiting on the person ahead of them.

To actually run in parallel, everyone must build against **fixed contracts (schemas) and
hand-written fixture files** instead of each other's live code. Nobody calls anybody else's
real function until the final integration pass. This is standard practice for parallelizing
a pipeline: freeze the interfaces first, mock everything upstream/downstream, integrate last.

---

## STEP 0 — Kickoff (all 4 people together, ~30 minutes, before splitting up)

Do this as a group, in one shared session/call, before anyone starts coding solo. This is the
only part of the project where sequencing matters — get it right and the rest is fully parallel.

Agree on and write these 4 files into the repo. Whoever is fastest can type while the others
review out loud:

```
schemas/finding.schema.json       — shape every agent (screen-reader/visual/motor) must emit
schemas/extraction.schema.json    — shape of Person 1's extraction pipeline output
schemas/report.schema.json        — shape of the final synthesized report
wcag/wcag22_criteria.json         — fixed list of WCAG 2.2 criteria agents may cite
```

**finding.schema.json** (JSON Schema draft-07):
```json
{
  "finding_id": "uuid string",
  "element_ref": "string, matches a data-a11y-id injected into the DOM",
  "agent": "screen_reader | visual | motor | axe_baseline",
  "issue_type": "e.g. missing_alt, meaningless_alt, low_contrast, unreachable, small_target, focus_trap, illogical_tab_order",
  "wcag_criterion": "string like 1.1.1 — MUST be present in wcag22_criteria.json",
  "severity": "critical | serious | moderate | minor",
  "evidence": "short factual string describing what was actually observed",
  "confidence": "float 0-1"
}
```

**extraction.schema.json** — combined output of Person 1's pipeline:
```json
{
  "page": "url or file path",
  "ax_tree": [ {"element_ref": "...", "role": "...", "name": "...", "description": "...", "states": {}} ],
  "css_findings": [ {"element_ref": "...", "contrast_ratio": 0.0, "is_large_text": false, "focus_indicator_visible": true} ],
  "keyboard_sim": {
    "traversal_order": ["element_ref", "..."],
    "unreachable": ["element_ref"],
    "illogical_jumps": [{"element_ref": "...", "note": "..."}],
    "trap_issues": [{"element_ref": "...", "note": "..."}],
    "small_targets": [{"element_ref": "...", "width": 0, "height": 0}]
  },
  "image_crops": [ {"element_ref": "...", "crop_path": "...", "claimed_alt": "..."} ],
  "zoom_screenshot_path": "string"
}
```

**report.schema.json** — final synthesis output:
```json
{
  "page": "string",
  "generated_at": "iso timestamp",
  "summary": {"critical": 0, "serious": 0, "moderate": 0, "minor": 0},
  "issues": [
    {
      "element_ref": "...",
      "wcag_criteria": ["1.1.1"],
      "severity": "critical",
      "agents_flagging": ["screen_reader", "motor"],
      "plain_language_description": "...",
      "recommended_fix": "...",
      "evidence": ["..."]
    }
  ]
}
```

**wcag22_criteria.json** — at minimum include: 1.1.1, 1.3.1, 1.4.3, 1.4.11, 2.1.1, 2.1.2, 2.4.3,
2.4.4, 2.4.6, 2.4.7, 2.5.8, 4.1.2 — each as `{"id": "1.1.1", "title": "...", "short_description": "..."}`.

Also agree in this kickoff on:
- Repo layout (below) and who owns which top-level folder, so there are no file collisions.
- The `data-a11y-id` convention: format `"a11y-<int>"`, injected once at the very start of
  extraction, before any other DOM reads. Everyone downstream treats this as the join key.
- Git workflow: 4 branches (`extraction`, `agents-sr-visual`, `agents-motor-synthesis`,
  `orchestrator-eval-ui`), merged into `main` only during the Step-4 integration pass.

Once these 4 files exist and are committed, **split into the 4 roles below and work fully in
parallel** — nobody needs to wait on anybody else's actual code until integration.

---

## Repo layout (agreed at kickoff, referenced by everyone)

```
a11yagents/
├── schemas/                (from kickoff — read-only for everyone after Step 0)
├── wcag/                   (from kickoff — read-only for everyone after Step 0)
├── fixtures/                     ← PERSON 1 publishes these early; everyone else consumes them
│   ├── extraction_good_page_1.json
│   ├── extraction_broken_page_1.json
│   ├── extraction_broken_page_2.json
│   └── extraction_mixed_page_1.json
├── extractor/              (PERSON 1)
├── test_pages/             (PERSON 1)
├── agents/
│   ├── base_agent.py       (PERSON 2 — shared helper, others import it)
│   ├── screen_reader_agent.py   (PERSON 2)
│   ├── visual_agent.py          (PERSON 2)
│   ├── motor_agent.py           (PERSON 3)
│   └── synthesis_agent.py       (PERSON 3)
├── baseline/                (PERSON 3)
├── orchestrator.py          (PERSON 4)
├── eval/                    (PERSON 4)
├── report_ui/               (PERSON 4)
├── mock_data/               ← PERSON 4 publishes early; also used by Person 3 for synthesis testing
│   └── sample_findings.json
└── README.md
```

---

## PERSON 1 — Extraction Pipeline + Test Pages + Fixtures

```
PROMPT FOR CLAUDE CODE — PERSON 1 (Extraction)

Project: A11yAgents. You own extraction and test pages, working in parallel with 3 teammates
who are building agents, synthesis, and orchestration/UI against the schemas below — they will
NOT touch your code, they only consume the fixture JSON files you publish. Your top priority
after getting basic extraction working is publishing fixtures/*.json early so teammates aren't
blocked, even before every extraction feature is polished.

Shared contracts already committed to the repo (read, do not modify):
schemas/extraction.schema.json, schemas/finding.schema.json, wcag/wcag22_criteria.json
(reproduce their contents here if not visible to you: [paste extraction.schema.json content]).
data-a11y-id convention: format "a11y-<int>", injected on every DOM element via page.evaluate()
BEFORE any other extraction step, so it's the stable join key for the whole project.

Build:
extractor/extract.py, extractor/ax_tree.py, extractor/css_snapshot.py, extractor/keyboard_sim.py,
extractor/screenshot_crop.py, baseline/run_axe.py, test_pages/*.html, fixtures/*.json

1. extract.py: Playwright-based. Loads URL or local HTML file. Injects data-a11y-id on every
   element first. Orchestrates the 4 extraction modules below and assembles one JSON object
   matching extraction.schema.json. Also captures a 200%-zoom full-page screenshot, saved to
   test_pages/_artifacts/, path recorded in the output.

2. ax_tree.py: Walk the Playwright accessibility tree IN READING ORDER (page.accessibility.snapshot()
   or CDP equivalent). For each node: {element_ref, role, name, description, states}. Cross-reference
   to data-a11y-id.

3. css_snapshot.py: For every text element, compute foreground/background color via
   getComputedStyle and calculate the actual WCAG contrast ratio yourself in code (implement
   relative luminance + contrast formula — do not leave this for an LLM to estimate later, agents
   downstream will treat your number as ground truth). For every focusable element, .focus() it
   and diff computed style (outline/box-shadow/border) vs unfocused state to detect missing focus
   indicators.

4. keyboard_sim.py — the highest-value, highest-risk piece. Do NOT simplify to reading tabindex
   attributes statically. Dispatch REAL key events: page.keyboard.press("Tab") repeatedly from
   document.body, recording document.activeElement's data-a11y-id after each press, building an
   ordered traversal list. Cross-reference against all interactive roles in the ax tree to find
   elements that never receive focus (unreachable). Detect illogical jumps (DOM order vs focus
   order divergence) and focus traps (dispatch Enter/Space on dialog/expandable elements, re-walk
   Tab to see if focus enters correctly and Escape returns it sensibly). Also compute bounding-box
   size for every interactive element for small-target detection (SC 2.5.8).

5. screenshot_crop.py: For every <img>, svg[role=img], and icon-only control, crop a screenshot
   of its bounding box, save under test_pages/_artifacts/crops/<element_ref>.png, and record the
   claimed accessible name/alt alongside the crop path — this pairing is what the screen-reader
   agent (Person 2) needs to judge alt-text meaningfulness.

6. baseline/run_axe.py: Inject axe-core (via add_script_tag with a local/CDN axe.min.js) and run
   axe.run() in-browser, return raw violations JSON (do not reshape to finding schema — that's
   Person 3's job in normalize_axe.py).

7. test_pages/*.html — hand-author 4 standalone HTML+inline-CSS+vanilla-JS files, no build step:
   - good_page_1.html: solid accessibility baseline (for false-positive checking).
   - broken_page_1.html: screen-reader issues — missing alt, alt="image.jpg", unlabeled inputs,
     "click here" links, skipped heading levels.
   - broken_page_2.html: motor/visual issues — unfocusable custom div-buttons, an inescapable
     JS focus trap modal, low-contrast text, `outline:none` with no replacement, 12x12px targets.
   - mixed_page_1.html: a realistic mix of both, so nothing downstream can pattern-match one
     failure type per page.

8. PUBLISH FIXTURES EARLY: as soon as extract.py runs end-to-end even partially, run it against
   all 4 test pages and commit the output JSON to fixtures/extraction_<pagename>.json. Re-publish
   whenever you make a meaningful fix. Post in the team channel each time you update these — this
   unblocks Persons 2 and 3 who are developing against these files, not live Playwright.

ACCEPTANCE CHECK: `python extractor/extract.py test_pages/broken_page_1.html` produces valid
JSON per extraction.schema.json with at least one missing-alt image + crop, a contrast_ratio
below 4.5 somewhere, and a non-trivial keyboard traversal. fixtures/*.json committed for all
4 pages.
```

---

## PERSON 2 — Screen-Reader Agent + Visual Agent + Shared Agent Helper

```
PROMPT FOR CLAUDE CODE — PERSON 2 (Screen-Reader + Visual Agents)

Project: A11yAgents. You own two of the three inspection agents plus the shared base_agent.py
helper that Person 3 will also import. You work in parallel with a teammate doing extraction —
DO NOT wait for their real pipeline. Develop against fixtures/extraction_*.json (hand-written
or provided by Person 1 early) which match schemas/extraction.schema.json.

Shared contracts (read, do not modify): schemas/finding.schema.json, wcag/wcag22_criteria.json
(reproduce here if not visible: [paste finding.schema.json + wcag list]).

If fixtures/*.json don't exist yet when you start, hand-write a minimal
fixtures/extraction_broken_page_1.json yourself matching extraction.schema.json exactly (a
handful of ax_tree nodes, a couple of css_findings, a small keyboard_sim object, 2-3 image_crops
with placeholder crop paths) so you're never blocked. Swap to Person 1's real fixtures the
moment they're published — the schema won't change, so this swap should be a non-event.

Build:
agents/base_agent.py, agents/screen_reader_agent.py, agents/visual_agent.py

1. base_agent.py (shared utility, Person 3 will import this too — keep it dependency-light
   and don't couple it to screen-reader/visual-specific logic):
   - Load wcag22_criteria.json and finding.schema.json once.
   - `call_claude(system_prompt, user_content, images=None)`: wraps Anthropic Python SDK
     messages.create. Support image content blocks (base64-encoded PNGs) alongside text.
   - `validate_findings(raw_json_str) -> list[dict]`: strip markdown fences if present,
     json.loads, validate each item against finding.schema.json via the `jsonschema` package,
     drop and log invalid entries rather than crashing.
   - `assign_uuid_if_missing(findings)`.

2. screen_reader_agent.py:
   - Input: ax_tree list + image_crops list from an extraction JSON (real or fixture).
   - For each image_crop: base64-encode the PNG (if the fixture crop_path doesn't exist on disk
     yet because Person 1 hasn't published real images, generate/use a placeholder PNG for your
     own local testing — swap once real crops exist), pass as an image block alongside its
     claimed alt text, ask Claude to judge: is alt present, does it accurately/sufficiently
     describe the image, is it boilerplate/filename-as-alt (counts as effectively missing).
   - From ax_tree (text-only): flag unlabeled form controls, meaningless link text ("click here"
     etc with no disambiguating context), heading structure problems (skipped levels, no h1,
     multiple h1s).
   - System prompt must require: wcag_criterion chosen only from the provided list; every
     finding has a concrete, non-generic evidence string.
   - Chunk image batches (e.g. ~10 per call) to handle an arbitrary number of crops.
   - Output: validated findings list, "agent": "screen_reader".

3. visual_agent.py:
   - Input: css_findings list (contrast_ratio, is_large_text, focus_indicator_visible — already
     numerically computed by Person 1, do not recompute or estimate in the LLM call) + zoom
     screenshot path as an image for qualitative reflow/overlap checking.
   - Apply WCAG threshold logic in code before calling the LLM (4.5:1 normal / 3:1 large text
     per SC 1.4.3) so the LLM's job is producing the finding record + severity judgment + evidence,
     not doing arithmetic.
   - Output: validated findings list, "agent": "visual".

4. Write agents/test_screen_reader_and_visual.py: a small standalone script/test that loads a
   fixture extraction JSON and runs both agents, printing validated findings — this is your own
   integration check, independent of anyone else's code.

ACCEPTANCE CHECK: running against fixtures/extraction_broken_page_1.json yields schema-valid
findings from both agents with real (in-list) WCAG criteria and concrete evidence strings.
Running against a "good page" fixture yields few/no findings.
```

---

## PERSON 3 — Motor Agent + Synthesis Agent + Axe Baseline Normalization

```
PROMPT FOR CLAUDE CODE — PERSON 3 (Motor Agent + Synthesis + Baseline)

Project: A11yAgents. You own the third inspection agent, the synthesis/merge agent, and axe-core
normalization. You work in parallel with 3 teammates — do not wait on their real code.
- For the motor agent: develop against fixtures/extraction_*.json (same as Person 2 — if not
  yet published, hand-write a minimal one yourself matching extraction.schema.json's keyboard_sim
  shape, swap to real fixtures later, schema won't change).
- For the synthesis agent: you do NOT need real agent output to build and test this. Hand-write
  mock_data/sample_findings.json yourself — a list of ~10-15 finding objects matching
  finding.schema.json, including some that deliberately share the same element_ref across
  different "agent" values (to test your dedup/compounding logic) — and develop entirely against
  that. Swap to real agent output only at integration time.

Shared contracts (read, do not modify): schemas/finding.schema.json, schemas/report.schema.json,
wcag/wcag22_criteria.json. Import agents/base_agent.py from Person 2 once it exists (it's a
small, stable file — coordinate directly with Person 2 if you need it before they've pushed it,
or stub a minimal version yourself temporarily with the same function signatures and swap later).

Build:
agents/motor_agent.py, agents/synthesis_agent.py, baseline/normalize_axe.py

1. motor_agent.py:
   - Input: keyboard_sim object from extraction JSON (traversal_order, unreachable,
     illogical_jumps, trap_issues, small_targets — real observed-behavior data, not raw tabindex).
   - Translate each raw signal into a finding record: unreachable → SC 2.1.1, illogical_jumps →
     SC 2.4.3, trap_issues → SC 2.1.2, small_targets → SC 2.5.8. Use ax_tree role/name (also in
     the extraction JSON) to judge severity — e.g. an unreachable primary call-to-action is worse
     than an unreachable decorative element.
   - Output: validated findings list, "agent": "motor".

2. synthesis_agent.py:
   - Input: a flat list of findings (real, from all 3 agents at integration time; mock_data/
     sample_findings.json while developing solo).
   - Step A (deterministic Python, NOT the LLM): group findings by element_ref. Where 2+ agents
     flagged the same element, keep that explicit (compounding issue) rather than dropping to
     one.
   - Step B (LLM call): per group, ask Claude to assign final severity (compounding issues should
     generally not rank below either individual issue), write ONE plain-language fix per group
     (not one per raw finding — avoid repeating near-identical advice), and order the full issue
     list by priority.
   - Output must validate against schemas/report.schema.json.

3. baseline/normalize_axe.py:
   - Reshape raw axe-core violations (Person 1's run_axe.py output — hand-write a small mock
     raw-axe-JSON fixture yourself if that's not published yet, axe's output format is
     well-documented/stable enough to mock confidently) into finding.schema.json shape,
     "agent": "axe_baseline". Map axe's rule/tag ids (e.g. "wcag143") to the closest id in
     wcag22_criteria.json.
   - Note: joining axe's CSS-selector-based node targeting to element_ref requires resolving
     back to the nearest data-a11y-id — write this as a function that takes a page handle +
     axe result and does the resolution; you'll wire it to Person 1's real page object at
     integration time, but the mapping LOGIC (rule id → WCAG criterion) can be fully built and
     tested against mocked axe JSON right now.

4. Write agents/test_synthesis.py: loads mock_data/sample_findings.json, runs synthesis_agent,
   prints/validates the report — your own integration check, independent of teammates.

ACCEPTANCE CHECK: synthesis_agent, run against your hand-written mock_data/sample_findings.json,
produces a schema-valid report.json where an element flagged by 2+ agents shows up once with
"agents_flagging" listing both, not as duplicate entries.
```

---

## PERSON 4 — Orchestrator + Evaluation Harness + Report UI

```
PROMPT FOR CLAUDE CODE — PERSON 4 (Orchestrator + Eval + UI)

Project: A11yAgents. You own gluing the pipeline together, scoring it, and the demo UI. You work
in parallel with 3 teammates building extraction/agents/synthesis — you do NOT wait for their
real code. Build orchestrator.py first against STUBBED functions, and build eval/report_ui
against a hand-written mock report.json. Swap stubs for real imports only at integration time.

Shared contracts (read, do not modify): schemas/extraction.schema.json, schemas/finding.schema.json,
schemas/report.schema.json, wcag/wcag22_criteria.json.

Build:
orchestrator.py, eval/score.py, eval/rubric_review.py, eval/ground_truth/ (structure only for now),
report_ui/, mock_data/sample_report.json, README.md (draft, others will add to it)

1. mock_data/sample_report.json — FIRST THING YOU DO. Hand-write a report.json matching
   schemas/report.schema.json with ~8-10 realistic issues spanning all severities and multiple
   agents_flagging combinations. This unblocks your own UI/eval work immediately AND gives
   Person 3 something to sanity-check their synthesis output's shape against.

2. orchestrator.py: 
   - `python orchestrator.py <path> --output report.json`
   - Flow: extract() → run 3 agents (concurrent or sequential) → collect findings → run axe
     baseline + normalize → synthesis_agent(findings) → validate → write report.json + a second
     report_with_axe_comparison.json (diff: agent_only_findings / axe_only_findings /
     overlapping_findings, joined on element_ref).
   - WHILE TEAMMATES' MODULES DON'T EXIST YET: import them via a thin try/except or a
     feature-flag pattern, e.g.:
     ```python
     try:
         from extractor.extract import extract
     except ImportError:
         def extract(path): 
             import json; return json.load(open("fixtures/extraction_broken_page_1.json"))
     ```
     Do this for every real dependency (extract, each agent, synthesis, run_axe, normalize_axe)
     so orchestrator.py runs and is testable from hour one, and quietly upgrades to real
     implementations as teammates push their code — no code change needed on your end.
   - Handle failures gracefully: if one stage errors, log and continue with partial results
     rather than crashing the whole run.

3. eval/score.py:
   - Given a report.json + a ground_truth/<page>.json (Person 1's test pages will need ground
     truth eventually — coordinate with Person 1 near the end of the build to hand-label the 4
     test pages together once test_pages/ is stable; this is the one place two roles should
     sync before full integration), compute precision/recall matched on (element_ref,
     wcag_criterion), with partial credit for same-element/different-but-related-criterion
     matches. Also computes agent_only_findings count/nature from report_with_axe_comparison.json
     as the headline "value beyond axe-core" metric.
   - Build and test this against mock_data/sample_report.json + a hand-written mock ground truth
     file first, so it's fully working before real reports exist.

4. eval/rubric_review.py: CLI script, loads a report.json, prints each issue's
   plain_language_description + recommended_fix, prompts a 1-5 score on clarity/prioritization/
   actionability, saves to eval/rubric_scores.json.

5. report_ui/: simplest thing that demos well — a single static HTML file + vanilla JS that
   fetches a report.json and renders: severity-badge summary counts at top, each issue as a card
   (severity, agents_flagging, WCAG criteria with titles pulled from wcag22_criteria.json, plain-
   language description, recommended fix), plus a clearly visible axe-core-only vs agent-only vs
   overlapping breakdown (this comparison is the project's key differentiator — make it visually
   prominent, not buried). Build and polish this entirely against mock_data/sample_report.json —
   it should look finished before a single real report exists.

6. README.md: start drafting now (setup steps, env vars, one-command demo instructions,
   architecture summary, known limitations) — leave clearly marked TODO sections for teammates
   to fill in details about their own modules at integration time.

ACCEPTANCE CHECK: report_ui renders mock_data/sample_report.json cleanly. eval/score.py runs
against a mock report + mock ground truth and prints sensible precision/recall numbers.
orchestrator.py runs end-to-end today, using fixtures/stubs, producing a valid report.json —
even before any teammate's real module lands.
```

---

## INTEGRATION PASS (all 4 people, last block of time — budget 2-3 hours)

Do this together, live, not solo:

1. **Merge order matters less than you'd think** since everyone built against schemas, but a
   sane order is: merge Person 1 (extraction) first, then Person 2 & 3 together (agents +
   synthesis), then Person 4's orchestrator last, since it's the one with the fallback stubs to
   remove.
2. In `orchestrator.py`, remove the try/except fixture-fallback shims one at a time, replacing
   with real imports, running the pipeline after each swap — this isolates exactly which
   integration point breaks if something doesn't match.
3. **Most likely real-world mismatches to check for, in order of likelihood:**
   - `element_ref` values not actually lining up between what Person 1's extractor assigns and
     what Person 3's axe normalization resolves back to — test this explicitly first.
   - Image crop file paths in fixtures vs. real crop paths from Person 1's screenshot_crop.py —
     Person 2's screen_reader_agent.py needs the real paths to exist on disk by integration time.
   - Minor schema drift if anyone quietly added an extra field during solo work — re-validate
     everyone's output against the committed schemas/*.json files, don't eyeball it.
4. Once orchestrator.py runs end-to-end for real on all 4 test pages, have Person 1 and Person 4
   sit together and hand-label `eval/ground_truth/*.json` (this was flagged as needing sync
   above) — this is the last piece of manual work and it's fast once real element_refs are known.
5. Run `eval/score.py` for real, drop the numbers into README.md, do a final pass through
   `report_ui` with real reports loaded, and you're done.
