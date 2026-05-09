"""Snapshot capture tool handlers."""

from __future__ import annotations

from .. import capture


def handle_capture_scene(cmd: dict) -> dict:
    def _do():
        return {"status": "success", "result": capture.capture_scene_snapshot()}

    from .handlers import execute_in_main_thread

    return execute_in_main_thread(_do)


def handle_capture_node_trees(cmd: dict) -> dict:
    def _do():
        return {"status": "success", "result": capture.capture_node_trees_snapshot()}

    from .handlers import execute_in_main_thread

    return execute_in_main_thread(_do)


def handle_capture_full(cmd: dict) -> dict:
    def _do():
        return {"status": "success", "result": capture.capture_full_snapshot()}

    from .handlers import execute_in_main_thread

    return execute_in_main_thread(_do)


__all__ = [
    "handle_capture_full",
    "handle_capture_node_trees",
    "handle_capture_scene",
]
