"""
screen_reader_agent.py — Person 2's first inspection agent.

Input: an extraction JSON object matching schemas/extraction.schema.json
(either real, from Person 1's pipeline, or a hand-written fixture).

Two passes:
  1. Image judgment: for each image_crop, show Claude the cropped PNG alongside
     its claimed alt text and ask whether the alt is present / accurate /
     sufficient, or effectively missing (boilerplate, filename-as-alt, etc).
  2. Text-only ax_tree pass: unlabeled form controls, meaningless link text
     ("click here" with no disambiguating context), and heading-structure
     problems (skipped levels, no h1, multiple h1s).

Output: a validated list of findings with "agent": "screen_reader".
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from base_agent import call_llm, validate_findings, load_wcag_criteria

logger = logging.getLogger("a11yagents.screen_reader_agent")

IMAGE_BATCH_SIZE = 10

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent
_PLACEHOLDER_CROP_DIR = _REPO_ROOT / "test_pages" / "_artifacts" / "crops"


def _wcag_list_str() -> str:
    criteria = load_wcag_criteria()
    lines = [f"- {cid}: {c['title']} — {c['short_description']}" for cid, c in criteria.items()]
    return "\n".join(lines)


def _resolve_crop_path(crop_path: str) -> Optional[str]:
    """Resolve a fixture's crop_path to something readable on disk.
    If the real path doesn't exist yet (Person 1 hasn't published real crops),
    fall back to a locally-generated placeholder PNG so development is never
    blocked. Swap is a non-event once real crops land, since we only change
    which file gets opened, not the calling convention."""
    if crop_path and Path(crop_path).exists():
        return crop_path

    # Fall back to a placeholder, generating one on first use.
    _PLACEHOLDER_CROP_DIR.mkdir(parents=True, exist_ok=True)
    placeholder = _PLACEHOLDER_CROP_DIR / "placeholder.png"
    if not placeholder.exists():
        _write_placeholder_png(placeholder)
    logger.info("screen_reader_agent: using placeholder image for missing crop_path %r", crop_path)
    return str(placeholder)


def _write_placeholder_png(path: Path) -> None:
    """Write a minimal 1x1 gray PNG so image-judgment calls have something to
    attach during local development before real crops exist."""
    import base64

    # 1x1 gray PNG, pre-encoded.
    tiny_png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBA"
        "SciXvQAAAAASUVORK5CYII="
    )
    path.write_bytes(base64.b64decode(tiny_png_b64))


IMAGE_SYSTEM_PROMPT = """You are an accessibility auditor judging whether an image's alt \
text is adequate for a screen-reader user.

For each image you are shown, you will also be given its claimed alt text and its \
element_ref. Decide:
- Is alt text present at all?
- Does it accurately and sufficiently describe the image's content/purpose?
- Is it boilerplate, a filename (e.g. "image.jpg", "IMG_1234.png"), or otherwise \
non-descriptive? Treat this as effectively missing.

Only flag a genuine problem — if the alt text is adequate, do not emit a finding for \
that image at all.

You MUST only choose wcag_criterion values from this fixed list (use the id exactly \
as written, e.g. "1.1.1"):
{wcag_list}

Respond with ONLY a JSON array (no markdown fences, no preamble) of finding objects, \
each with exactly these fields:
  finding_id: "" (leave empty, will be assigned later)
  element_ref: the element_ref you were given for that image
  agent: "screen_reader"
  issue_type: one of "missing_alt", "meaningless_alt"
  wcag_criterion: from the list above (image alt issues are almost always "1.1.1")
  severity: "critical" | "serious" | "moderate" | "minor"
  evidence: a short, concrete, non-generic factual string describing what you actually \
observed (e.g. "alt text is the literal filename 'banner2.jpg'", not "alt text is bad")
  confidence: float between 0 and 1

If no images have problems, respond with an empty JSON array: []
"""

TEXT_SYSTEM_PROMPT = """You are an accessibility auditor reviewing a page's accessibility \
tree (ax_tree) for screen-reader issues that are NOT about images.

Look for:
- Unlabeled form controls (role indicates an input/textbox/checkbox/etc but name is \
empty or missing) -> issue_type "missing_alt" is for images only; use \
issue_type "unlabeled_control" here, wcag_criterion "4.1.2" (or "1.3.1" if it's more \
about programmatic structure than name/role/value).
- Meaningless link text: link name is generic and gives no context on its own ("click \
here", "read more", "link", "here") with nothing in the surrounding tree to disambiguate \
-> issue_type "meaningless_link_text", wcag_criterion "2.4.4".
- Heading structure problems: skipped heading levels (e.g. h1 -> h3 with no h2), no h1 \
present at all, or multiple h1s on the page -> issue_type "heading_structure", \
wcag_criterion "1.3.1".

Only flag genuine problems found in the given tree. Do not invent elements that are not \
present.

You MUST only choose wcag_criterion values from this fixed list:
{wcag_list}

Respond with ONLY a JSON array (no markdown fences, no preamble) of finding objects, \
each with exactly these fields:
  finding_id: "" (leave empty)
  element_ref: the element_ref of the offending element (for heading-structure issues \
with no single offending element, use the element_ref of the heading where the problem \
becomes apparent, e.g. the h3 that skipped a level)
  agent: "screen_reader"
  issue_type: as described above
  wcag_criterion: from the list above
  severity: "critical" | "serious" | "moderate" | "minor"
  evidence: short, concrete, non-generic factual string
  confidence: float between 0 and 1

If there are no problems, respond with an empty JSON array: []
"""


def _judge_images(image_crops: list[dict]) -> list[dict]:
    if not image_crops:
        return []

    findings: list[dict] = []
    wcag_list = _wcag_list_str()
    system_prompt = IMAGE_SYSTEM_PROMPT.format(wcag_list=wcag_list)

    for i in range(0, len(image_crops), IMAGE_BATCH_SIZE):
        batch = image_crops[i : i + IMAGE_BATCH_SIZE]
        images = []
        manifest = []
        for crop in batch:
            resolved = _resolve_crop_path(crop.get("crop_path", ""))
            if resolved is None:
                continue
            images.append(resolved)
            manifest.append(
                {"element_ref": crop["element_ref"], "claimed_alt": crop.get("claimed_alt", "")}
            )

        if not images:
            continue

        user_content = (
            "Here are the images in this batch, in order, with their element_ref and "
            "claimed alt text:\n" + json.dumps(manifest, indent=2)
        )

        try:
            raw = call_llm(system_prompt, user_content, images=images)
        except Exception as e:  # noqa: BLE001 - one bad batch shouldn't kill the whole run
            logger.error("screen_reader_agent: image batch call failed: %s", e)
            continue

        findings.extend(validate_findings(raw))

    return findings


def _judge_ax_tree_text(ax_tree: list[dict]) -> list[dict]:
    if not ax_tree:
        return []

    wcag_list = _wcag_list_str()
    system_prompt = TEXT_SYSTEM_PROMPT.format(wcag_list=wcag_list)
    user_content = "Here is the ax_tree for this page:\n" + json.dumps(ax_tree, indent=2)

    try:
        raw = call_llm(system_prompt, user_content)
    except Exception as e:  # noqa: BLE001
        logger.error("screen_reader_agent: ax_tree text call failed: %s", e)
        return []

    return validate_findings(raw)


def run(extraction: dict) -> list[dict]:
    """Entry point: takes a full extraction.schema.json-shaped dict, returns
    validated findings from both the image and text passes, agent="screen_reader"."""
    ax_tree = extraction.get("ax_tree", [])
    image_crops = extraction.get("image_crops", [])

    findings: list[dict] = []
    findings.extend(_judge_images(image_crops))
    findings.extend(_judge_ax_tree_text(ax_tree))
    return findings


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else str(
        _REPO_ROOT / "fixtures" / "extraction_broken_page_1.json"
    )
    with open(path, "r", encoding="utf-8") as f:
        extraction_data = json.load(f)

    results = run(extraction_data)
    print(json.dumps(results, indent=2))
