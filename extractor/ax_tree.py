"""
ax_tree.py — Module for extracting the accessibility tree via CDP
and cross-referencing nodes to their data-a11y-id.
"""

from __future__ import annotations
import logging
from typing import Any
from playwright.async_api import Page

logger = logging.getLogger("a11yagents.extractor.ax_tree")

def _traverse_dom_for_mapping(node: dict[str, Any], mapping: dict[int, str]) -> None:
    """Recursively traverse the CDP DOM tree to build a mapping from backendNodeId to data-a11y-id."""
    backend_id = node.get("backendNodeId")
    attrs = node.get("attributes", [])
    if backend_id is not None and attrs:
        for i in range(0, len(attrs), 2):
            if attrs[i] == "data-a11y-id":
                mapping[backend_id] = attrs[i + 1]
                break
    
    # Process children
    for child in node.get("children", []):
        _traverse_dom_for_mapping(child, mapping)
    
    # Process shadow DOMs if any
    for shadow in node.get("shadowRoots", []):
        _traverse_dom_for_mapping(shadow, mapping)
        
    # Process content documents (for iframes)
    content_doc = node.get("contentDocument")
    if content_doc:
        _traverse_dom_for_mapping(content_doc, mapping)

async def get_ax_tree(page: Page) -> list[dict[str, Any]]:
    """
    Retrieves the Chrome DevTools Protocol (CDP) Accessibility tree and
    maps each node to its corresponding data-a11y-id.
    """
    # Start a CDP Session
    client = await page.context.new_cdp_session(page)
    await client.send("DOM.enable")
    await client.send("Accessibility.enable")
    
    # Get the DOM document recursively to fetch backendNodeId to attributes mapping
    logger.info("Fetching DOM document for backendNodeId mapping...")
    dom_doc = await client.send("DOM.getDocument", {"depth": -1, "pierce": True})
    
    backend_to_a11y_id: dict[int, str] = {}
    if "root" in dom_doc:
        _traverse_dom_for_mapping(dom_doc["root"], backend_to_a11y_id)
        
    logger.info("Mapped %d elements to data-a11y-id", len(backend_to_a11y_id))
    
    # Fetch the full accessibility tree
    logger.info("Fetching full AX tree via CDP...")
    ax_tree_res = await client.send("Accessibility.getFullAXTree")
    ax_nodes = ax_tree_res.get("nodes", [])
    
    result_tree: list[dict[str, Any]] = []
    
    for node in ax_nodes:
        # Ignore nodes that are ignored by default in the AX tree
        if node.get("ignored", False):
            continue
            
        backend_id = node.get("backendDOMNodeId")
        if backend_id is None or backend_id not in backend_to_a11y_id:
            continue
            
        element_ref = backend_to_a11y_id[backend_id]
        
        # Extract role
        role_val = ""
        role_obj = node.get("role")
        if isinstance(role_obj, dict):
            role_val = role_obj.get("value", "")
        elif isinstance(role_obj, str):
            role_val = role_obj
            
        # Extract name
        name_val = ""
        name_obj = node.get("name")
        if isinstance(name_obj, dict):
            name_val = name_obj.get("value", "")
        elif isinstance(name_obj, str):
            name_val = name_obj
            
        # Extract description
        desc_val = ""
        desc_obj = node.get("description")
        if isinstance(desc_obj, dict):
            desc_val = desc_obj.get("value", "")
        elif isinstance(desc_obj, str):
            desc_val = desc_obj
            
        # Extract states from properties
        states: dict[str, Any] = {}
        for prop in node.get("properties", []):
            prop_name = prop.get("name")
            prop_val_obj = prop.get("value", {})
            if prop_name and "value" in prop_val_obj:
                states[prop_name] = prop_val_obj["value"]
                
        result_tree.append({
            "element_ref": element_ref,
            "role": role_val,
            "name": name_val,
            "description": desc_val,
            "states": states
        })
        
    return result_tree
