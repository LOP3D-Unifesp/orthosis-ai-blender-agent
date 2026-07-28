"""TCP socket bridge running inside Blender.

Listens on localhost:65432 by default, or on the per-process port selected by
``ORTHOSIS_BRIDGE_PORT``. Each connection receives one JSON command and returns
one JSON response. Protocol: 8-byte ASCII length prefix + UTF-8 JSON.

All commands are dispatched through HANDLERS in tools/handlers.py.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
import traceback

from .tools.handlers import HANDLERS

DEFAULT_HOST = "localhost"
FALLBACK_PORT = 65432
PORT_ENV_VAR = "ORTHOSIS_BRIDGE_PORT"
RECV_CHUNK = 65536


def _configured_port() -> int:
    """Return the per-process bridge port, falling back to the project default."""
    raw = os.environ.get(PORT_ENV_VAR, "").strip()
    if not raw:
        return FALLBACK_PORT
    try:
        port = int(raw)
    except ValueError:
        print(f"[Bridge] Ignoring invalid {PORT_ENV_VAR}={raw!r}; using {FALLBACK_PORT}")
        return FALLBACK_PORT
    if not 1 <= port <= 65535:
        print(f"[Bridge] Ignoring out-of-range {PORT_ENV_VAR}={raw!r}; using {FALLBACK_PORT}")
        return FALLBACK_PORT
    return port


DEFAULT_PORT = _configured_port()


class BlenderBridgeServer:
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self._thread: threading.Thread | None = None
        self._running = False
        self._sock: socket.socket | None = None
        self._last_connection_at: str = ""

    @property
    def running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

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
                self._last_connection_at = time.strftime("%H:%M:%S")
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
        handler = HANDLERS.get(cmd_type)
        if handler is None:
            self._send(conn, {
                "status": "error",
                "error": f"Unknown command: {cmd_type!r}",
                "available": sorted(HANDLERS.keys()),
            })
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


def register():
    _server.start()


def unregister():
    _server.stop()
