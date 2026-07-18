"""
keyboard_sim.py — Module for simulating keyboard interactions and analyzing focus flows.
"""

from __future__ import annotations
import logging
from typing import Any
from playwright.async_api import Page

logger = logging.getLogger("a11yagents.extractor.keyboard_sim")

async def get_keyboard_sim(page: Page, ax_tree: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Simulates keyboard interaction on the page.
    Returns keyboard traversal order, unreachable elements, illogical jumps,
    focus trap issues, and small targets.
    """
    logger.info("Starting keyboard simulation...")
    
    # 1. Focus the body first to reset focus location
    try:
        await page.click("body")
    except Exception:
        pass
    await page.focus("body")
    await page.wait_for_timeout(100)
    
    # 2. Sequential Tab traversal
    traversal_order: list[str] = []
    visited_refs = set()
    
    # Max 100 tab presses to prevent infinite loop on traps
    for _ in range(100):
        await page.keyboard.press("Tab")
        # Wait a small timeout for any focus transition animation or script
        await page.wait_for_timeout(50)
        
        active_ref = await page.evaluate(
            "document.activeElement && document.activeElement !== document.body ? document.activeElement.getAttribute('data-a11y-id') : null"
        )
        
        if not active_ref:
            # We reached body or outside the page
            break
            
        if traversal_order and active_ref == traversal_order[0]:
            # Cycled back to the first element
            break
            
        if len(traversal_order) > 0 and active_ref == traversal_order[-1]:
            # Focus is stuck on the same element
            break
            
        if active_ref in visited_refs:
            # Detected a smaller loop
            traversal_order.append(active_ref)
            break
            
        traversal_order.append(active_ref)
        visited_refs.add(active_ref)
        
    logger.info("Keyboard traversal order: %s", traversal_order)
    
    # 3. Identify all interactive/focusable elements currently visible on the page
    interactive_refs = await page.evaluate("""
        () => {
            const list = [];
            const selectors = 'a, button, input, textarea, select, details, [tabindex], [role="button"], [role="link"], [role="checkbox"]';
            const elements = document.querySelectorAll(selectors);
            for (const el of elements) {
                // Visibility check
                if (el.offsetWidth > 0 || el.offsetHeight > 0) {
                    const ref = el.getAttribute('data-a11y-id');
                    if (ref) {
                        list.push(ref);
                    }
                }
            }
            return list;
        }
    """)
    
    # Unreachable elements (interactive, but never received focus during Tabbing)
    unreachable = [ref for ref in interactive_refs if ref not in visited_refs]
    
    # 4. Illogical jumps: Focus order vs DOM order index jumps
    illogical_jumps: list[dict[str, Any]] = []
    for i in range(len(traversal_order) - 1):
        ref_curr = traversal_order[i]
        ref_next = traversal_order[i + 1]
        
        try:
            idx_curr = int(ref_curr.split("-")[1])
            idx_next = int(ref_next.split("-")[1])
            
            # Focus went backward in DOM index
            if idx_next < idx_curr:
                # Make sure they are not just adjacent elements with reversed tabindex,
                # but flag it as a potential illogical jump.
                illogical_jumps.append({
                    "element_ref": ref_next,
                    "note": f"Focus jumped backward from {ref_curr} (DOM index {idx_curr}) to {ref_next} (DOM index {idx_next})."
                })
        except (ValueError, IndexError):
            continue
            
    # 5. Focus Trap Simulation:
    # Look for elements that might open modals/popups, click them, check if we get stuck or if Esc fails.
    trap_issues: list[dict[str, Any]] = []
    
    # Find potential triggers
    trigger_refs = await page.evaluate("""
        () => {
            const list = [];
            const elements = document.querySelectorAll('button, a, [role="button"]');
            for (const el of elements) {
                if (!(el.offsetWidth > 0 || el.offsetHeight > 0)) continue;
                
                const ref = el.getAttribute('data-a11y-id');
                const text = (el.innerText || "").toLowerCase();
                const hasPopup = el.getAttribute('aria-haspopup');
                
                if (ref && (hasPopup === 'dialog' || hasPopup === 'true' || text.includes('open') || text.includes('modal') || text.includes('dialog'))) {
                    list.push(ref);
                }
            }
            return list;
        }
    """)
    
    for trigger_ref in trigger_refs:
        logger.info("Testing trigger for focus trap: %s", trigger_ref)
        try:
            # Focus and click the trigger
            await page.focus(f'[data-a11y-id="{trigger_ref}"]')
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(300)  # Wait for modal to open
            
            # Tab up to 10 times to see if we get stuck or loop
            modal_visited = []
            for _ in range(10):
                await page.keyboard.press("Tab")
                await page.wait_for_timeout(50)
                active = await page.evaluate("document.activeElement ? document.activeElement.getAttribute('data-a11y-id') : null")
                if not active:
                    break
                if modal_visited and active == modal_visited[0]:
                    break
                if len(modal_visited) > 0 and active == modal_visited[-1]:
                    break
                modal_visited.append(active)
                
            # Press Escape to close modal
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(300)
            
            # Check if focus is returned to trigger
            active_after = await page.evaluate("document.activeElement ? document.activeElement.getAttribute('data-a11y-id') : null")
            if active_after != trigger_ref:
                # If focus is not returned to the trigger, or if we were stuck inside
                trap_issues.append({
                    "element_ref": trigger_ref,
                    "note": f"After activating trigger and pressing Escape, focus did not return to the trigger. Active element: {active_after}."
                })
        except Exception as e:
            logger.warning("Error during focus trap simulation on %s: %s", trigger_ref, e)
            continue
            
    # 6. Small targets detection (target size smaller than 24x24 px)
    small_targets = await page.evaluate("""
        () => {
            const list = [];
            const interactiveSelectors = 'a, button, input, textarea, select, [role="button"], [role="link"], [role="checkbox"]';
            const elements = document.querySelectorAll(interactiveSelectors);
            for (const el of elements) {
                if (!(el.offsetWidth > 0 || el.offsetHeight > 0)) continue;
                
                const ref = el.getAttribute('data-a11y-id');
                if (ref) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width < 24 || rect.height < 24) {
                        list.push({
                            element_ref: ref,
                            width: Math.round(rect.width),
                            height: Math.round(rect.height)
                        });
                    }
                }
            }
            return list;
        }
    """)
    
    return {
        "traversal_order": traversal_order,
        "unreachable": unreachable,
        "illogical_jumps": illogical_jumps,
        "trap_issues": trap_issues,
        "small_targets": small_targets
    }
