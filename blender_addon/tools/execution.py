"""Generic code execution tool handler."""

from __future__ import annotations

import io
import json
import traceback
from contextlib import redirect_stderr, redirect_stdout


def _json_safe(value):
    """Best-effort conversion of a patch ``result`` into JSON-safe data."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "__iter__") and not isinstance(value, (bytes, bytearray)):
        try:
            return [_json_safe(v) for v in value]
        except Exception:
            return str(value)
    return str(value)


def handle_execute_code(cmd: dict) -> dict:
    """Execute a Python patch inside Blender.

    Returns captured ``stdout`` and ``stderr``. For structured output the patch
    may assign a JSON-serializable object to a variable named ``result`` in its
    namespace; it comes back under the ``result`` key (json-safe coerced). This
    avoids having to ``print()`` and re-parse data on the client side.
    """
    code = cmd.get("code", "")

    def _do():
        import bpy

        out = io.StringIO()
        err = io.StringIO()
        namespace = {"bpy": bpy, "__builtins__": __builtins__}
        try:
            with redirect_stdout(out), redirect_stderr(err):
                exec(code, namespace, namespace)
            response = {
                "status": "success",
                "stdout": out.getvalue(),
                "stderr": err.getvalue(),
            }
            if "result" in namespace:
                try:
                    response["result"] = _json_safe(namespace["result"])
                except Exception as exc:
                    response["result_error"] = f"result not serializable: {exc}"
            return response
        except Exception as exc:
            return {
                "status": "error",
                "error": str(exc),
                "stdout": out.getvalue(),
                "stderr": err.getvalue(),
                "traceback": traceback.format_exc(),
            }

    from .handlers import execute_in_main_thread

    return execute_in_main_thread(_do)


__all__ = ["handle_execute_code"]
