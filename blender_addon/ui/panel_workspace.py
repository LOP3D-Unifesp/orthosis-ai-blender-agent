"""Workspace text, attachment, prompt-buffer, and draft execution helpers."""

from __future__ import annotations

import re
import traceback
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import bpy

from .chat_session import SESSION
from ._helpers import _normalize_multiline_text
from . import panel_runtime as _runtime
from .cycle_state import _get_work_cycle_info

# Text / file helpers
# ---------------------------------------------------------------------------

_TEXT_ATTACHMENT_EXTENSIONS = {".json", ".txt", ".md", ".py", ".log", ".yaml", ".yml", ".csv"}
_MAX_ATTACHMENT_BYTES = 1024 * 1024
_MAX_ATTACHMENT_CHARS = 120_000


def _read_text_attachment(filepath: str) -> dict[str, str | int | bool]:
    path = Path(filepath)
    if not path.exists() or not path.is_file():
        raise RuntimeError("Selected file does not exist.")
    ext = path.suffix.lower()
    if ext not in _TEXT_ATTACHMENT_EXTENSIONS:
        supported = ", ".join(sorted(_TEXT_ATTACHMENT_EXTENSIONS))
        raise RuntimeError(f"Unsupported file type '{ext or '[none]'}'. Supported: {supported}")

    raw = path.read_bytes()
    original_bytes = len(raw)
    truncated = False
    if len(raw) > _MAX_ATTACHMENT_BYTES:
        raw = raw[:_MAX_ATTACHMENT_BYTES]
        truncated = True

    text: str | None = None
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except Exception:
            continue
    if text is None:
        raise RuntimeError("Could not decode file as text.")

    normalized = _normalize_multiline_text(text).strip()
    if len(normalized) > _MAX_ATTACHMENT_CHARS:
        normalized = normalized[:_MAX_ATTACHMENT_CHARS].rstrip() + "\n...[file truncated]"
        truncated = True
    if not normalized:
        raise RuntimeError("Selected file is empty.")

    return {
        "path": str(path),
        "name": path.name,
        "extension": ext,
        "text": normalized,
        "bytes": original_bytes,
        "truncated": truncated,
    }


def _build_file_context_blocks(file_attachments: list[dict[str, str | int | bool]]) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    for item in file_attachments:
        name = str(item.get("name", "") or "attachment")
        ext = str(item.get("extension", "") or "")
        path = str(item.get("path", "") or "")
        truncated = bool(item.get("truncated", False))
        text = str(item.get("text", "") or "").strip()
        if not text:
            continue
        header = f"[Attached File]\nName: {name}\nType: {ext or 'text'}\nPath: {path}"
        if truncated:
            header += "\nNote: file content was truncated before sending."
        blocks.append({"type": "text", "text": header + "\n\n" + text})
    return blocks


# ---------------------------------------------------------------------------
# Prompt buffer helpers
# ---------------------------------------------------------------------------

def _get_prompt_buffer(scene: bpy.types.Scene | None = None, *, create: bool = True) -> bpy.types.Text | None:
    text_block = None
    if scene is not None:
        candidate = getattr(scene, "chat_prompt_buffer", None)
        if candidate is not None and getattr(candidate, "name", "") in bpy.data.texts:
            text_block = candidate
    if text_block is None:
        text_block = bpy.data.texts.get(_PROMPT_BUFFER_NAME)
    if text_block is None and create:
        text_block = bpy.data.texts.new(_PROMPT_BUFFER_NAME)
    if text_block is not None and scene is not None:
        try:
            scene.chat_prompt_buffer = text_block
        except Exception:
            pass
    return text_block


def _replace_text_block_contents(text_block: bpy.types.Text, value: str) -> None:
    normalized = _normalize_multiline_text(value)
    text_block.clear()
    if normalized:
        text_block.write(normalized)


def _seed_prompt_buffer_from_input(scene: bpy.types.Scene, text_block: bpy.types.Text) -> None:
    buffer_text = _normalize_multiline_text(text_block.as_string())
    input_text = _normalize_multiline_text(getattr(scene, "chat_input", "") or "")
    if input_text.strip() and not buffer_text.strip():
        _replace_text_block_contents(text_block, input_text)


def _find_text_editor_area(screen: bpy.types.Screen) -> bpy.types.Area | None:
    for area in screen.areas:
        if area.type == "TEXT_EDITOR":
            return area
    return None


def _preferred_split_area(screen: bpy.types.Screen, fallback: bpy.types.Area | None) -> bpy.types.Area | None:
    preferred_types = {"NODE_EDITOR", "VIEW_3D"}
    candidates = [area for area in screen.areas if area.type in preferred_types]
    if candidates:
        return max(candidates, key=lambda area: area.width * area.height)
    return fallback


def _open_text_block_in_workspace(context, text_block: bpy.types.Text) -> bool:
    screen = context.window.screen
    area = _find_text_editor_area(screen)
    if area is None:
        split_source = _preferred_split_area(screen, context.area)
        if split_source is None:
            return False
        area_ids_before = {candidate.as_pointer() for candidate in screen.areas}
        with context.temp_override(window=context.window, screen=screen, area=split_source):
            bpy.ops.screen.area_split(direction="VERTICAL", factor=0.72)
        new_areas = [candidate for candidate in screen.areas if candidate.as_pointer() not in area_ids_before]
        if new_areas:
            area = max(new_areas, key=lambda candidate: candidate.width * candidate.height)
            area.type = "TEXT_EDITOR"
        else:
            area = _find_text_editor_area(screen)
    if area is None or area.type != "TEXT_EDITOR":
        return False
    space = area.spaces.active
    space.text = text_block
    if hasattr(space, "show_word_wrap"):
        space.show_word_wrap = True
    if hasattr(space, "show_line_numbers"):
        space.show_line_numbers = True
    return True


def _open_prompt_buffer_in_workspace(context, text_block: bpy.types.Text) -> bool:
    return _open_text_block_in_workspace(context, text_block)


def _draft_block_name_from_session() -> str:
    try:
        info = _get_work_cycle_info()
        blend_path = str(info.get("blend_path", "") or "")
        rt = _runtime._get_runtime()
        session = rt.runtime.v1_session_for(blend_path)
        es = getattr(session, "execution_state", None)
        draft = getattr(es, "current_draft", None) if es is not None else None
        return str(
            getattr(draft, "block_name", "")
            or getattr(es, "draft_block_name", "")
            or "GN_Agent_Draft"
        )
    except Exception:
        return "GN_Agent_Draft"


def _open_current_draft_in_workspace(context) -> tuple[bool, str]:
    block_name = _draft_block_name_from_session()
    text_block = bpy.data.texts.get(block_name)
    if text_block is None:
        return False, f"Draft '{block_name}' nao existe no Text Editor."
    if not _open_text_block_in_workspace(context, text_block):
        return False, f"Draft '{block_name}' existe, mas nao consegui abrir um Text Editor automaticamente."
    return True, block_name


def _draft_tree_name_from_text_block(text_block: bpy.types.Text | None) -> str:
    if text_block is None:
        return ""
    try:
        prop_value = str(text_block.get("_draft_tree_name", "") or "").strip()
        if prop_value:
            return prop_value
    except Exception:
        pass
    try:
        content = text_block.as_string()
    except Exception:
        content = ""
    match = re.search(
        r"node_groups\.(?:get\(\s*|\[\s*)[\"']([^\"']+)[\"']",
        str(content or ""),
    )
    return match.group(1).strip() if match else ""


def _tree_node_count(tree_name: str) -> int | None:
    if not tree_name:
        return None
    tree = bpy.data.node_groups.get(tree_name)
    if tree is None:
        return None
    try:
        return len(tree.nodes)
    except Exception:
        return None


def _run_current_draft_text(context) -> tuple[bool, str]:
    opened, detail = _open_current_draft_in_workspace(context)
    if not opened:
        return False, detail

    text_block = bpy.data.texts.get(detail)
    tree_name = _draft_tree_name_from_text_block(text_block)
    node_count_before = _tree_node_count(tree_name)

    try:
        code = text_block.as_string() if text_block is not None else ""
    except Exception:
        code = ""
    if not code.strip():
        return False, f"Draft '{detail}' esta vazio."
    stdout = StringIO()
    try:
        globals_dict = {
            "__name__": "__main__",
            "__file__": f"<Blender Text:{detail}>",
            "bpy": bpy,
        }
        with redirect_stdout(stdout):
            exec(compile(code, f"<Blender Text:{detail}>", "exec"), globals_dict, globals_dict)
    except Exception as exc:
        tb_tail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        return False, f"Erro ao rodar '{detail}': {tb_tail}"
    node_count_after = _tree_node_count(tree_name)
    output = stdout.getvalue().strip()
    output_hint = f" | print: {output[:160]}" if output else ""
    if tree_name and node_count_before is not None and node_count_after is not None:
        delta = node_count_after - node_count_before
        return True, f"{detail} em '{tree_name}' (nos: {node_count_before} -> {node_count_after}, delta {delta:+d}){output_hint}"
    if tree_name:
        return True, f"{detail} em '{tree_name}'{output_hint}"
    return True, f"{detail}{output_hint}"


# ---------------------------------------------------------------------------
