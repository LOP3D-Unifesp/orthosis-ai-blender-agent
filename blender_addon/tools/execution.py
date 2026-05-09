"""Generic code execution tool handler."""

from __future__ import annotations

import io
import traceback
from contextlib import redirect_stdout


def handle_execute_code(cmd: dict) -> dict:
    code = cmd.get("code", "")

    def _do():
        import bpy

        buf = io.StringIO()
        try:
            namespace = {"bpy": bpy, "__builtins__": __builtins__}
            with redirect_stdout(buf):
                exec(code, namespace, namespace)
            return {"status": "success", "stdout": buf.getvalue()}
        except Exception as exc:
            return {
                "status": "error",
                "error": str(exc),
                "stdout": buf.getvalue(),
                "traceback": traceback.format_exc(),
            }

    from .handlers import execute_in_main_thread

    return execute_in_main_thread(_do)


__all__ = ["handle_execute_code"]
