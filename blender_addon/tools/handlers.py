"""Blender-side command handlers — direct dispatch without policy gate.

This is the execution layer for the TCP bridge (server.py). All entries in
HANDLERS are callable with a single dict argument and return a dict response.
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
from .execution import handle_execute_code
from .reads import (
    handle_find_tree_nodes,
    handle_get_active_frame_context,
    handle_get_local_subgraph_context,
    handle_get_node_context,
    handle_get_selected_nodes_context,
    handle_list_tree_nodes,
)
from .snapshots import handle_capture_full, handle_capture_node_trees, handle_capture_scene
from .validation_tools import (
    handle_add_node,
    handle_evaluate_geometry,
    handle_link_sockets,
    handle_render_viewport,
    handle_resolve_node,
    handle_set_node_input,
    handle_set_param,
)


# Ordered below the server conn timeout (30s) and the client timeout (60s) so a
# slow main-thread op fails here first with a clean message instead of a socket
# reset.
_MAIN_THREAD_TIMEOUT = 25.0


def execute_in_main_thread(func):
    """Run ``func`` on Blender's main thread and block until completion.

    If the main thread does not pick up the work before the deadline we mark the
    job cancelled and return a timeout error. The cancellation flag is checked
    inside the timer callback so a late-firing timer does NOT run ``func`` (and
    therefore cannot apply a mutation) after the caller already gave up. This
    closes the orphaned-timer hazard where a patch could land silently after a
    reported timeout.
    """
    result: dict[str, Any] = {}
    state = {"cancelled": False}

    def _wrapper():
        if state["cancelled"]:
            return None
        try:
            result["data"] = func()
        except Exception as exc:
            result["data"] = {
                "status": "error",
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        return None

    if threading.current_thread() is threading.main_thread():
        _wrapper()
        return result["data"]

    bpy.app.timers.register(_wrapper)
    deadline = time.monotonic() + _MAIN_THREAD_TIMEOUT
    while "data" not in result:
        if time.monotonic() > deadline:
            state["cancelled"] = True
            return {
                "status": "error",
                "error": "Blender main thread did not respond within "
                         f"{_MAIN_THREAD_TIMEOUT:.0f}s (job cancelled; no mutation applied).",
            }
        time.sleep(0.005)
    return result["data"]


HANDLERS = {
    # Scene / tree inspection
    "capture_scene": handle_capture_scene,
    "capture_node_trees": handle_capture_node_trees,
    "capture_full": handle_capture_full,
    # Node reads
    "list_tree_nodes": handle_list_tree_nodes,
    "find_tree_nodes": handle_find_tree_nodes,
    "get_node_context": handle_get_node_context,
    "get_selected_nodes_context": handle_get_selected_nodes_context,
    "get_active_frame_context": handle_get_active_frame_context,
    "get_local_subgraph_context": handle_get_local_subgraph_context,
    # Execution
    "execute_code": handle_execute_code,
    # Validation + typed mutations
    "evaluate_geometry": handle_evaluate_geometry,
    "render_viewport": handle_render_viewport,
    "set_param": handle_set_param,
    "resolve_node": handle_resolve_node,
    "set_node_input": handle_set_node_input,
    "link_sockets": handle_link_sockets,
    "add_node": handle_add_node,
    # Biomodel source (consolidation path)
    "seed_biomodel_source": handle_seed_biomodel_source,
    "read_biomodel_source": handle_read_biomodel_source,
    "write_biomodel_source": handle_write_biomodel_source,
    "validate_biomodel_source": handle_validate_biomodel_source,
}
