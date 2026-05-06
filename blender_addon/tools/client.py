"""TCP socket client for dispatching tool calls to Blender."""

from __future__ import annotations

import json
import socket
from typing import Any


DEFAULT_HOST = "localhost"
DEFAULT_PORT = 65432
RECV_CHUNK = 65536


def _recv_exact(sock: socket.socket, count: int) -> bytes:
    data = b""
    while len(data) < count:
        chunk = sock.recv(min(RECV_CHUNK, count - len(data)))
        if not chunk:
            break
        data += chunk
    return data


def _recv_until_close(sock: socket.socket) -> bytes:
    data = b""
    try:
        while True:
            chunk = sock.recv(RECV_CHUNK)
            if not chunk:
                break
            data += chunk
    except socket.timeout:
        pass
    return data


def call_blender_socket(
    command: dict[str, Any],
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = 60.0,
) -> dict[str, Any]:
    payload = json.dumps(command, ensure_ascii=False).encode("utf-8")
    header = f"{len(payload):08d}".encode("ascii")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        sock.sendall(header + payload)

        raw_header = _recv_exact(sock, 8)
        if not raw_header or not raw_header.isdigit():
            data = (raw_header or b"") + _recv_until_close(sock)
            if not data:
                return {"status": "error", "error": "Blender não está respondendo (resposta vazia). Verifique se o addon está ativo na porta 65432."}
            try:
                return json.loads(data.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as _e:
                return {"status": "error", "error": f"Blender retornou resposta inválida: {_e}"}

        expected_len = int(raw_header)
        data = _recv_exact(sock, expected_len)
        if not data:
            return {"status": "error", "error": "Blender não está respondendo (corpo da resposta vazio)."}
        try:
            return json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as _e:
            return {"status": "error", "error": f"Blender retornou resposta inválida: {_e}"}
    finally:
        sock.close()


def dispatch_tool_raw(
    tool_name: str,
    tool_input: dict[str, Any] | None = None,
    *,
    route: str = "product",
    output_mode: str = "compact",
    user_confirmed: bool = True,
    debug_mode: bool | None = None,
    explicit_override_mode: bool | None = None,
    mcp_write_enabled: bool | None = None,
    blend_path: str | None = None,
    journal_session_id: str | None = None,
    journal_run_id: str | None = None,
    journal_goal_id: str | None = None,
) -> dict[str, Any]:
    if tool_name == "execute_code" and isinstance(tool_input, dict):
        if not tool_input.get("code") and tool_input.get("script"):
            tool_input = dict(tool_input)
            tool_input["code"] = tool_input.get("script", "")
            tool_input.pop("script", None)
    command = {
        "type": "runtime_tool_call",
        "tool_name": tool_name,
        "tool_input": tool_input or {},
        "route": route,
        "output_mode": output_mode,
        "user_confirmed": bool(user_confirmed),
    }
    if debug_mode is not None:
        command["debug_mode"] = bool(debug_mode)
    if explicit_override_mode is not None:
        command["explicit_override_mode"] = bool(explicit_override_mode)
    if mcp_write_enabled is not None:
        command["mcp_write_enabled"] = bool(mcp_write_enabled)
    if blend_path is not None:
        command["blend_path"] = str(blend_path)
    if journal_session_id:
        command["journal_session_id"] = str(journal_session_id)
    if journal_run_id:
        command["journal_run_id"] = str(journal_run_id)
    if journal_goal_id:
        command["journal_goal_id"] = str(journal_goal_id)
    return call_blender_socket(command)
