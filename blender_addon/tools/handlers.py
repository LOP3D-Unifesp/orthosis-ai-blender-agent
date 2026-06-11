"""Blender-side command handlers executed on the main thread.

This module is the low-level execution layer used by runtime dispatch.
"""

from __future__ import annotations

import threading
import time
import traceback
from typing import Any

import bpy

from .biomodel_source import (
    handle_read_biomodel_source,
    handle_seed_biomodel_source,
    handle_validate_biomodel_source,
    handle_write_biomodel_source,
)
from .draft import handle_read_script_draft, handle_write_script_draft
from .edits import handle_apply_collections, handle_apply_gn_edits, handle_apply_renames
from .execution import handle_execute_code
from .query import handle_query_node_types
from .reads import (
    handle_find_tree_nodes,
    handle_get_active_frame_context,
    handle_get_local_subgraph_context,
    handle_get_node_context,
    handle_get_selected_nodes_context,
    handle_list_tree_nodes,
)
from .snapshots import handle_capture_full, handle_capture_node_trees, handle_capture_scene


_MAIN_THREAD_TIMEOUT = 15.0  # seconds before giving up waiting for Blender main thread


def execute_in_main_thread(func):
    """Run ``func`` on Blender's main thread and block until completion.

    Raises RuntimeError if the main thread does not respond within
    _MAIN_THREAD_TIMEOUT seconds (e.g. blocked by a modal operator).
    """
    result: dict[str, Any] = {}

    def _wrapper():
        try:
            result["data"] = func()
        except Exception as exc:
            result["data"] = {
                "status": "error",
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }

    if threading.current_thread() is threading.main_thread():
        _wrapper()
        return result["data"]

    bpy.app.timers.register(_wrapper)
    deadline = time.monotonic() + _MAIN_THREAD_TIMEOUT
    while "data" not in result:
        if time.monotonic() > deadline:
            return {
                "status": "error",
                "error": "Blender main thread did not respond within "
                         f"{_MAIN_THREAD_TIMEOUT:.0f}s. A modal operator may "
                         "be blocking execution.",
            }
        time.sleep(0.01)
    return result["data"]


# ---------------------------------------------------------------------------
# Script drafting handlers (staged script drafting mode)
# ---------------------------------------------------------------------------

HANDLERS = {
    "capture_scene": handle_capture_scene,
    "capture_node_trees": handle_capture_node_trees,
    "capture_full": handle_capture_full,
    "get_node_context": handle_get_node_context,
    "get_selected_nodes_context": handle_get_selected_nodes_context,
    "get_active_frame_context": handle_get_active_frame_context,
    "get_local_subgraph_context": handle_get_local_subgraph_context,
    "list_tree_nodes": handle_list_tree_nodes,
    "find_tree_nodes": handle_find_tree_nodes,
    "apply_renames": handle_apply_renames,
    "apply_collections": handle_apply_collections,
    "apply_gn_edits": handle_apply_gn_edits,
    "execute_code": handle_execute_code,
    "query_node_types": handle_query_node_types,
    "write_script_draft": handle_write_script_draft,
    "read_script_draft": handle_read_script_draft,
    "seed_biomodel_source": handle_seed_biomodel_source,
    "read_biomodel_source": handle_read_biomodel_source,
    "write_biomodel_source": handle_write_biomodel_source,
    "validate_biomodel_source": handle_validate_biomodel_source,
}
