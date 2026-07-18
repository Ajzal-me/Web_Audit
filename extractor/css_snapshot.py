"""
css_snapshot.py — Module for measuring text contrast and focus indicator visibility.
"""

from __future__ import annotations
import logging
import re
from typing import Any
from playwright.async_api import Page

logger = logging.getLogger("a11yagents.extractor.css_snapshot")

def _parse_rgb(color_str: str) -> tuple[int, int, int]:
    """Parse 'rgb(r, g, b)' or 'rgba(r, g, b, a)' into an (r, g, b) tuple."""
    match = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", color_str)
    if match:
        return int(match.group(1)), int(match.group(2)), int(match.group(3))
    return 255, 255, 255  # default to white

def _relative_luminance(color: tuple[int, int, int]) -> float:
    """Calculate the relative luminance of an RGB color."""
    rgb = []
    for c in color:
        s = c / 255.0
        if s <= 0.03928:
            rgb.append(s / 12.92)
        else:
            rgb.append(((s + 0.055) / 1.055) ** 2.4)
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]

def _contrast_ratio(color1: tuple[int, int, int], color2: tuple[int, int, int]) -> float:
    """Calculate the contrast ratio between two RGB colors."""
    l1 = _relative_luminance(color1)
    l2 = _relative_luminance(color2)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)

async def get_css_findings(page: Page) -> list[dict[str, Any]]:
    """
    Evaluates computed styles for text elements (contrast ratio) and focusable elements (focus ring check).
    Returns a list of elements with contrast ratios, large text flags, and focus indicator visibility.
    """
    logger.info("Injecting script to get CSS properties of elements...")
    
    js_extract_script = """
    () => {
        const results = {
            textElements: [],
            focusableElements: []
        };
        
        // 1. Find visible text elements
        const allElements = document.querySelectorAll('*');
        for (const el of allElements) {
            // Basic visibility check
            if (!(el.offsetWidth > 0 || el.offsetHeight > 0)) {
                continue;
            }
            
            // Check for direct non-empty text nodes
            let hasDirectText = false;
            for (const node of el.childNodes) {
                if (node.nodeType === Node.TEXT_NODE && node.nodeValue.trim().length > 0) {
                    hasDirectText = true;
                    break;
                }
            }
            
            const elementRef = el.getAttribute('data-a11y-id');
            if (hasDirectText && elementRef) {
                const style = window.getComputedStyle(el);
                const fontSizePx = parseFloat(style.fontSize);
                const fontWeight = style.fontWeight;
                const isBold = fontWeight === 'bold' || parseInt(fontWeight) >= 700;
                const isLargeText = fontSizePx >= 24 || (fontSizePx >= 18.66 && isBold);
                
                // Resolve background color (walk up tree for transparency)
                let bg = style.backgroundColor;
                let temp = el;
                while ((bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent') && temp.parentElement) {
                    temp = temp.parentElement;
                    bg = window.getComputedStyle(temp).backgroundColor;
                }
                if (bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent') {
                    bg = 'rgb(255, 255, 255)';
                }
                
                results.textElements.push({
                    element_ref: elementRef,
                    fg: style.color,
                    bg: bg,
                    is_large_text: isLargeText
                });
            }
        }
        
        // 2. Find focusable elements
        const focusableSelectors = 'a, button, input, textarea, select, details, [tabindex]';
        const focusables = document.querySelectorAll(focusableSelectors);
        for (const el of focusables) {
            if (!(el.offsetWidth > 0 || el.offsetHeight > 0)) {
                continue;
            }
            
            const elementRef = el.getAttribute('data-a11y-id');
            if (elementRef) {
                const style = window.getComputedStyle(el);
                results.focusableElements.push({
                    element_ref: elementRef,
                    before: {
                        outline: style.outline,
                        outlineColor: style.outlineColor,
                        outlineWidth: style.outlineWidth,
                        outlineStyle: style.outlineStyle,
                        boxShadow: style.boxShadow,
                        borderColor: style.borderColor,
                        borderWidth: style.borderWidth,
                        borderStyle: style.borderStyle
                    }
                });
            }
        }
        
        // 3. Focus and capture style after focus
        const originalActive = document.activeElement;
        for (const item of results.focusableElements) {
            const el = document.querySelector(`[data-a11y-id="${item.element_ref}"]`);
            if (el) {
                try {
                    el.focus();
                    const style = window.getComputedStyle(el);
                    item.after = {
                        outline: style.outline,
                        outlineColor: style.outlineColor,
                        outlineWidth: style.outlineWidth,
                        outlineStyle: style.outlineStyle,
                        boxShadow: style.boxShadow,
                        borderColor: style.borderColor,
                        borderWidth: style.borderWidth,
                        borderStyle: style.borderStyle
                    };
                } catch (e) {
                    // Ignore focus errors
                    item.after = item.before;
                }
            } else {
                item.after = item.before;
            }
        }
        
        // Restore focus
        if (originalActive && typeof originalActive.focus === 'function') {
            originalActive.focus();
        } else if (document.activeElement) {
            document.activeElement.blur();
        }
        
        return results;
    }
    """
    
    extracted = await page.evaluate(js_extract_script)
    
    # Process text elements (compute contrast)
    contrast_map: dict[str, dict[str, Any]] = {}
    for text_el in extracted["textElements"]:
        ref = text_el["element_ref"]
        fg_rgb = _parse_rgb(text_el["fg"])
        bg_rgb = _parse_rgb(text_el["bg"])
        ratio = round(_contrast_ratio(fg_rgb, bg_rgb), 2)
        
        # Keep the worst contrast ratio if element has multiple text nodes
        if ref in contrast_map:
            if ratio < contrast_map[ref]["contrast_ratio"]:
                contrast_map[ref]["contrast_ratio"] = ratio
        else:
            contrast_map[ref] = {
                "element_ref": ref,
                "contrast_ratio": ratio,
                "is_large_text": text_el["is_large_text"],
                # We'll fill this in next step
                "focus_indicator_visible": True
            }
            
    # Process focusable elements
    focus_map: dict[str, bool] = {}
    for item in extracted["focusableElements"]:
        ref = item["element_ref"]
        before = item["before"]
        after = item.get("after", before)
        
        # Diff key style attributes
        changed = False
        for key in before:
            if before[key] != after.get(key):
                changed = True
                break
        
        # Also check if focused state outline/box-shadow is non-existent
        # e.g. if before had no outline, and after has no outline either, focus is invisible.
        # Browsers usually default to showing one, but developers might override with outline: none
        # If they override it, outlineStyle is 'none' and boxShadow is 'none' / 'rgba(0, 0, 0, 0)'.
        # Let's consider focus indicator visible if it changed.
        focus_map[ref] = changed

    # Assemble final findings list
    findings: list[dict[str, Any]] = []
    
    # Combined set of all element references we found
    all_refs = set(contrast_map.keys()).union(focus_map.keys())
    
    for ref in all_refs:
        # Default properties
        contrast_ratio = 21.0  # Perfect contrast as default
        is_large_text = False
        focus_visible = True
        
        if ref in contrast_map:
            contrast_ratio = contrast_map[ref]["contrast_ratio"]
            is_large_text = contrast_map[ref]["is_large_text"]
            
        if ref in focus_map:
            focus_visible = focus_map[ref]
            
        findings.append({
            "element_ref": ref,
            "contrast_ratio": contrast_ratio,
            "is_large_text": is_large_text,
            "focus_indicator_visible": focus_visible
        })
        
    return findings
