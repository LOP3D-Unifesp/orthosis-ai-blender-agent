"""TCP socket bridge running inside Blender.

Supports:
  - direct low-level handlers (capture_scene, execute_code, etc.)
  - unified runtime endpoints (runtime_tool_call, runtime_set_modes, runtime_get_session)
"""

from __future__ import annotations

import json
import socket
import threading
import traceback
from pathlib import Path

from .handlers import HANDLERS
from .project_paths import resolve_project_root
from .runtime import Runtime


DEFAULT_HOST = "localhost"
DEFAULT_PORT = 65432
RECV_CHUNK = 65536


def _resolve_project_root() -> Path:
    """Resolve project root for session/journal persistence."""
    return resolve_project_root()


# Compatibility alias for callers and tests that still import the old name
# during the convergence window. The live socket path now instantiates
# Runtime directly.
RuntimeBridgeCore = Runtime


class BlenderBridgeServer:
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self._thread: threading.Thread | None = None
        self._running = False
        self._sock: socket.socket | None = None
        project_root = _resolve_project_root()
        self._runtime = Runtime(project_root=project_root)

    @property
    def running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    def refresh_runtime(self) -> Path:
        project_root = _resolve_project_root()
        current_root = Path(getattr(self._runtime, "project_root", project_root))
        if current_root != project_root:
            self._runtime = Runtime(project_root=project_root)
        return project_root

    def start(self):
        if self.running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        print(f"[Bridge] Server started on {self.host}:{self.port}")

    def stop(self):
        self._running = False
        try:
            wake = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            wake.settimeout(0.5)
            wake.connect((self.host, self.port))
            wake.close()
        except Exception:
            pass
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        print("[Bridge] Server stopped")

    def _listen_loop(self):
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind((self.host, self.port))
            self._sock.listen(1)
            self._sock.settimeout(0.5)
            while self._running:
                try:
                    conn, _ = self._sock.accept()
                except socket.timeout:
                    continue
                if not self._running:
                    conn.close()
                    break
                try:
                    self._handle_connection(conn)
                except Exception as exc:
                    print(f"[Bridge] Connection error: {exc}")
                finally:
                    conn.close()
        except Exception as exc:
            print(f"[Bridge] Server error: {exc}")
            traceback.print_exc()
        finally:
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None

    def _handle_connection(self, conn: socket.socket):
        conn.settimeout(30.0)
        raw = self._recv_all(conn)
        if not raw:
            return

        try:
            cmd = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._send(conn, {"status": "error", "error": f"Invalid JSON: {exc}"})
            return

        cmd_type = cmd.get("type", "")
        if cmd_type == "runtime_tool_call":
            try:
                response = self._runtime.execute_tool_call(
                    tool_name=cmd.get("tool_name", ""),
                    tool_input=cmd.get("tool_input", {}) or {},
                    route=cmd.get("route", "mcp"),
                    output_mode=cmd.get("output_mode", "compact"),
                    user_confirmed=bool(cmd.get("user_confirmed", False)),
                    debug_mode=cmd.get("debug_mode"),
                    explicit_override_mode=cmd.get("explicit_override_mode"),
                    mcp_write_enabled=cmd.get("mcp_write_enabled"),
                    blend_path=cmd.get("blend_path"),
                    journal_session_id=cmd.get("journal_session_id"),
                    journal_run_id=cmd.get("journal_run_id"),
                    journal_goal_id=cmd.get("journal_goal_id"),
                )
            except Exception as exc:
                response = {
                    "status": "error",
                    "error": f"runtime_tool_call crashed server-side: {exc}",
                    "tool_name": cmd.get("tool_name", ""),
                    "traceback": traceback.format_exc(),
                }
            self._send(conn, response)
            return

        if cmd_type == "runtime_set_modes":
            state = self._runtime.set_modes(
                blend_path=cmd.get("blend_path"),
                debug_mode=cmd.get("debug_mode"),
                explicit_override_mode=cmd.get("explicit_override_mode"),
                mcp_write_enabled=cmd.get("mcp_write_enabled"),
                agent_session_active=cmd.get("agent_session_active"),
                reset_session_memory=bool(cmd.get("reset_session_memory", False)),
                start_new_session=bool(cmd.get("start_new_session", False)),
                approval_plan_id=cmd.get("approval_plan_id"),
                approval_token=cmd.get("approval_token"),
                approval_decision=cmd.get("approval_decision"),
                approval_source=cmd.get("approval_source"),
                clear_pending_plan=bool(cmd.get("clear_pending_plan", False)),
                clear_approval_state=bool(cmd.get("clear_approval_state", False)),
                reset_transient_state=bool(cmd.get("reset_transient_state", False)),
                rebuild_plan=bool(cmd.get("rebuild_plan", False)),
                control_source=cmd.get("control_source"),
                claim_control_owner=bool(cmd.get("claim_control_owner", False)),
                force_control_owner=bool(cmd.get("force_control_owner", False)),
                control_owner_enforced=cmd.get("control_owner_enforced"),
                clear_control_owner=bool(cmd.get("clear_control_owner", False)),
                drafting_mode=cmd.get("drafting_mode"),
                simulate_bridge_failure=cmd.get("simulate_bridge_failure"),
            )
            if bool(state.get("control_update_blocked", False)):
                self._send(
                    conn,
                    {
                        "status": "blocked",
                        "error": "Control update blocked by single control owner policy.",
                        "result": state,
                    },
                )
            else:
                self._send(conn, {"status": "success", "result": state})
            return

        if cmd_type == "runtime_get_session":
            state = self._runtime.get_session_state(blend_path=cmd.get("blend_path"))
            self._send(conn, {"status": "success", "result": state})
            return

        handler = HANDLERS.get(cmd_type)
        if handler is None:
            self._send(
                conn,
                {
                    "status": "error",
                    "error": f"Unknown command: {cmd_type}",
                    "available": list(HANDLERS.keys()) + [
                        "runtime_tool_call",
                        "runtime_set_modes",
                        "runtime_get_session",
                    ],
                },
            )
            return

        try:
            response = handler(cmd)
        except Exception as exc:
            response = {"status": "error", "error": str(exc), "traceback": traceback.format_exc()}
        self._send(conn, response)

    def _recv_all(self, conn: socket.socket) -> bytes:
        first = conn.recv(RECV_CHUNK)
        if not first:
            return b""

        if len(first) >= 8 and first[:8].isdigit():
            expected = int(first[:8])
            data = first[8:]
            while len(data) < expected:
                chunk = conn.recv(RECV_CHUNK)
                if not chunk:
                    break
                data += chunk
            return data

        data = first
        try:
            json.loads(data)
            return data
        except json.JSONDecodeError:
            pass

        conn.settimeout(1.0)
        while True:
            try:
                chunk = conn.recv(RECV_CHUNK)
                if not chunk:
                    break
                data += chunk
                try:
                    json.loads(data)
                    return data
                except json.JSONDecodeError:
                    continue
            except socket.timeout:
                break
        return data

    @staticmethod
    def _send(conn: socket.socket, response: dict):
        payload = json.dumps(response, ensure_ascii=False).encode("utf-8")
        header = f"{len(payload):08d}".encode("ascii")
        conn.sendall(header + payload)


_server = BlenderBridgeServer()


def refresh_runtime_project_root() -> Path:
    return _server.refresh_runtime()


def register():
    _server.start()


def unregister():
    _server.stop()
