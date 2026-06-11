"""Chat session state — module-level singleton, no Blender dependency.

This module is intentionally free of ``bpy`` imports so that unit tests
can exercise ``_ChatSession`` directly without a running Blender instance.
"""

from __future__ import annotations

import re
import threading


_STREAM_CODE_MARKER_RE = re.compile(
    r"\b(import\s+bpy|bpy\.data|tree\s*=|nodes\s*=|links\s*=|def\s+\w+|class\s+\w+|write_script_draft|GeometryNodeTree)\b",
    re.IGNORECASE,
)
_STREAM_CODE_LINE_RE = re.compile(
    r"^\s*(import\s+\w+|from\s+\w+\s+import|def\s+\w+|class\s+\w+|if\s+.+:|for\s+.+:|while\s+.+:|try:|except\b|with\s+.+:|"
    r"[A-Za-z_]\w*\s*=|[A-Za-z_]\w*\.[A-Za-z_]\w*\s*=|print\s*\(|raise\s+|return\b|bpy\.|tree\.|nodes\.|links\.|#)",
    re.IGNORECASE,
)
_FENCED_CODE_RE = re.compile(
    r"```(?:python|py|bpy)?\s*\n.*?\n```",
    re.IGNORECASE | re.DOTALL,
)
_CODE_OMITTED_TEXT = "[codigo omitido no painel; qualquer draft deve ser salvo no Text Editor]"


def _looks_like_code_stream(text: str) -> bool:
    body = str(text or "")
    if "```" in body:
        return True
    if _STREAM_CODE_MARKER_RE.search(body):
        return True
    nonempty = [line for line in body.splitlines() if line.strip()]
    if len(nonempty) < 4:
        return False
    codey = sum(1 for line in nonempty if _STREAM_CODE_LINE_RE.search(line))
    return codey >= 4 and codey / max(1, len(nonempty)) >= 0.45


def _sanitize_visible_assistant_text(text: str) -> str:
    """Keep final assistant messages readable without dumping Python drafts."""
    body = str(text or "")
    if not body:
        return ""

    body = _FENCED_CODE_RE.sub(_CODE_OMITTED_TEXT, body)
    if not _STREAM_CODE_MARKER_RE.search(body):
        return body

    sanitized: list[str] = []
    code_run = 0
    omitted = False
    for line in body.splitlines():
        if _STREAM_CODE_LINE_RE.search(line):
            code_run += 1
            if code_run >= 4 and not omitted:
                while sanitized and _STREAM_CODE_LINE_RE.search(sanitized[-1]):
                    sanitized.pop()
                sanitized.append(_CODE_OMITTED_TEXT)
                omitted = True
            continue
        code_run = 0
        omitted = False
        sanitized.append(line)
    return "\n".join(sanitized).strip()


class _ChatSession:
    """In-memory chat state that survives panel redraws.

    Owned exclusively by the UI layer.  Shared between the panel,
    background worker thread, and screenshot capture thread through the
    module-level ``SESSION`` singleton below.
    """

    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.running: bool = False
        self.current_tool: str = ""
        self.tool_call_count: int = 0
        self.streaming_text: str = ""
        self.stream_blocked: bool = False
        self.reasoning_text: str = ""
        self.error: str = ""
        self.pending_screenshots: list[bytes] = []
        self.pending_files: list[dict[str, str | int | bool]] = []
        self.screenshot_running: bool = False
        self.screenshot_notice: str = ""
        self.session_notice: str = ""
        self.loaded_session_id: str = ""
        self.last_turn_input_tokens: int = 0
        self.last_turn_output_tokens: int = 0
        self.session_input_tokens: int = 0
        self.session_output_tokens: int = 0
        self._lock = threading.Lock()

    def add(self, role: str, text: str) -> None:
        if str(role or "").strip().lower() == "assistant":
            text = _sanitize_visible_assistant_text(text)
        with self._lock:
            self.messages.append({"role": role, "text": text})

    def get_messages(self) -> list[dict]:
        with self._lock:
            return list(self.messages)

    def clear(self) -> None:
        with self._lock:
            self.messages.clear()
            self.running = False
            self.error = ""
            self.current_tool = ""
            self.tool_call_count = 0
            self.streaming_text = ""
            self.stream_blocked = False
            self.reasoning_text = ""
            self.pending_screenshots = []
            self.pending_files = []
            self.screenshot_running = False
            self.screenshot_notice = ""
            self.session_notice = ""
            self.loaded_session_id = ""
            self.last_turn_input_tokens = 0
            self.last_turn_output_tokens = 0
            self.session_input_tokens = 0
            self.session_output_tokens = 0

    def replace_messages(self, messages: list[dict], *, session_id: str = "") -> None:
        normalized: list[dict] = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "")).strip().lower()
            if role not in {"user", "assistant"}:
                continue
            text = str(item.get("text", "") or "")
            if not text.strip():
                continue
            if role == "assistant":
                text = _sanitize_visible_assistant_text(text)
            normalized.append({"role": role, "text": text})
        with self._lock:
            self.messages = normalized
            self.loaded_session_id = str(session_id or "")

    def update_session_id(self, session_id: str) -> None:
        """Track a new session_id without touching the visible message list.

        Called when the session switches (e.g. user saves the .blend for the
        first time) but the new session has no persisted history yet.  Advancing
        the ID here prevents _sync_ui_messages_from_session from re-firing on
        every draw cycle while still keeping the currently visible messages.
        """
        with self._lock:
            self.loaded_session_id = str(session_id or "")

    def reset_turn(self) -> None:
        """Reset per-turn state when starting a new request."""
        with self._lock:
            self.current_tool = ""
            self.tool_call_count = 0
            self.streaming_text = ""
            self.stream_blocked = False
            self.reasoning_text = ""
            self.error = ""

    def append_stream_chunk(self, chunk: str) -> None:
        with self._lock:
            if self.stream_blocked:
                return
            candidate = self.streaming_text + str(chunk or "")
            if _looks_like_code_stream(candidate):
                self.streaming_text = _CODE_OMITTED_TEXT
                self.stream_blocked = True
                return
            self.streaming_text = candidate

    # ------------------------------------------------------------------
    # Screenshot queue
    # ------------------------------------------------------------------

    def add_screenshot(self, png_bytes: bytes) -> int:
        with self._lock:
            self.pending_screenshots.append(png_bytes)
            return len(self.pending_screenshots)

    def consume_screenshots(self) -> list[bytes]:
        with self._lock:
            data = list(self.pending_screenshots)
            self.pending_screenshots = []
            return data

    def pending_screenshot_count(self) -> int:
        with self._lock:
            return len(self.pending_screenshots)

    # ------------------------------------------------------------------
    # File attachment queue
    # ------------------------------------------------------------------

    def add_file_attachment(self, entry: dict[str, str | int | bool]) -> int:
        with self._lock:
            self.pending_files.append(dict(entry))
            return len(self.pending_files)

    def consume_file_attachments(self) -> list[dict[str, str | int | bool]]:
        with self._lock:
            return [dict(item) for item in self.pending_files]

    def pending_file_count(self) -> int:
        with self._lock:
            return len(self.pending_files)

    def set_screenshot_notice(self, text: str) -> None:
        with self._lock:
            self.screenshot_notice = text

    def set_session_notice(self, text: str) -> None:
        with self._lock:
            self.session_notice = text


# Module-level singleton — the single source of UI state for the panel.
SESSION = _ChatSession()
