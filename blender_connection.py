"""TCP client for connecting to the Blender bridge addon.

Used by the MCP server process to send commands to Blender and receive
responses. Matches the protocol in blender_addon/server.py:
length-prefix (8 ASCII digits) + JSON payload.
"""

from __future__ import annotations

import json
import socket


DEFAULT_HOST = "localhost"
DEFAULT_PORT = 65432
TIMEOUT = 60.0  # seconds


class BlenderConnectionError(Exception):
    """Raised when communication with Blender fails."""
    pass


class BlenderConnection:
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.host = host
        self.port = port

    def send_command(self, cmd: dict) -> dict:
        """Send a JSON command to Blender and return the parsed response."""
        payload = json.dumps(cmd, ensure_ascii=False).encode("utf-8")
        header = f"{len(payload):08d}".encode("ascii")
        sock = None

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(TIMEOUT)
            sock.connect((self.host, self.port))
            sock.sendall(header + payload)

            # Read response: 8-byte length prefix + JSON
            response_data = self._recv_response(sock)
            return json.loads(response_data.decode("utf-8"))

        except ConnectionRefusedError:
            raise BlenderConnectionError(
                f"Cannot connect to Blender at {self.host}:{self.port}. "
                "Make sure Blender is running and the bridge addon is started."
            )
        except socket.timeout:
            raise BlenderConnectionError(
                f"Timeout waiting for Blender response (>{TIMEOUT}s). "
                "The operation may be too complex or Blender may be unresponsive."
            )
        except json.JSONDecodeError as exc:
            raise BlenderConnectionError(f"Invalid JSON response from Blender: {exc}")
        except Exception as exc:
            raise BlenderConnectionError(f"Blender connection error: {exc}")
        finally:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass

    def _recv_response(self, sock: socket.socket) -> bytes:
        """Receive a length-prefixed response."""
        # Read 8-byte header
        header = b""
        while len(header) < 8:
            chunk = sock.recv(8 - len(header))
            if not chunk:
                raise BlenderConnectionError("Connection closed before header received")
            header += chunk

        expected_len = int(header.decode("ascii"))
        data = b""
        while len(data) < expected_len:
            chunk = sock.recv(min(65536, expected_len - len(data)))
            if not chunk:
                break
            data += chunk
        return data

    def ping(self) -> bool:
        """Test if Blender is reachable."""
        try:
            result = self.send_command({"type": "capture_scene"})
            return result.get("status") == "success"
        except BlenderConnectionError:
            return False

    # ----- Convenience methods -----

    def capture_scene(self) -> dict:
        result = self.send_command({"type": "capture_scene"})
        if result.get("status") != "success":
            raise BlenderConnectionError(f"Capture failed: {result.get('error', 'unknown')}")
        return result["result"]

    def capture_node_trees(self) -> dict:
        result = self.send_command({"type": "capture_node_trees"})
        if result.get("status") != "success":
            raise BlenderConnectionError(f"Capture failed: {result.get('error', 'unknown')}")
        return result["result"]

    def capture_full(self) -> dict:
        result = self.send_command({"type": "capture_full"})
        if result.get("status") != "success":
            raise BlenderConnectionError(f"Capture failed: {result.get('error', 'unknown')}")
        return result["result"]

    def list_tree_nodes(self, tree_name: str) -> dict:
        """List all nodes in a GN tree. Direct read, no policy gates."""
        return self.send_command({"type": "list_tree_nodes", "tree_name": tree_name})

    def find_tree_nodes(self, tree_name: str, *, name_contains: str = "", label_contains: str = "", bl_idname: str = "") -> dict:
        """Search nodes by name/label/type fragment. Direct read, no policy gates."""
        cmd: dict = {"type": "find_tree_nodes", "tree_name": tree_name}
        if name_contains:
            cmd["name_contains"] = name_contains
        if label_contains:
            cmd["label_contains"] = label_contains
        if bl_idname:
            cmd["bl_idname"] = bl_idname
        return self.send_command(cmd)

    def get_node_context(self, tree_name: str, node_name: str, *, radius: int = 1) -> dict:
        """Read one node and its neighborhood. Direct read, no policy gates."""
        return self.send_command({
            "type": "get_node_context",
            "tree_name": tree_name,
            "node_name": node_name,
            "radius": radius,
        })

    def execute_code(self, code: str) -> dict:
        return self.send_command({"type": "execute_code", "code": code})

    # ----- Validation + typed mutations -----

    def evaluate_geometry(self, obj: str, *, sample: int = 0) -> dict:
        return self.send_command({"type": "evaluate_geometry", "object": obj, "sample": sample})

    def render_viewport(self, obj: str, *, view: str = "iso", path: str = "", resolution: int = 640) -> dict:
        cmd: dict = {"type": "render_viewport", "object": obj, "view": view, "resolution": resolution}
        if path:
            cmd["path"] = path
        return self.send_command(cmd)

    def set_param(self, obj: str, identifier: str, value) -> dict:
        return self.send_command({"type": "set_param", "object": obj, "identifier": identifier, "value": value})

    def resolve_node(self, tree_name: str, ref: str) -> dict:
        return self.send_command({"type": "resolve_node", "tree_name": tree_name, "ref": ref})

    def set_node_input(self, tree_name: str, node: str, socket, value) -> dict:
        return self.send_command({
            "type": "set_node_input", "tree_name": tree_name, "node": node, "socket": socket, "value": value,
        })

    def link_sockets(self, tree_name: str, from_node: str, from_socket, to_node: str, to_socket) -> dict:
        return self.send_command({
            "type": "link_sockets", "tree_name": tree_name,
            "from_node": from_node, "from_socket": from_socket,
            "to_node": to_node, "to_socket": to_socket,
        })

    def add_node(self, tree_name: str, bl_idname: str, **kwargs) -> dict:
        cmd = {"type": "add_node", "tree_name": tree_name, "bl_idname": bl_idname}
        cmd.update(kwargs)
        return self.send_command(cmd)
