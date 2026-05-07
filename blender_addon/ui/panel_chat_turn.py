"""Background chat turn worker and send-message entry point."""

from __future__ import annotations

import base64
import threading

from .chat_session import SESSION
from . import panel_runtime as _runtime
from .panel_workspace import _build_file_context_blocks

# Background worker
# ---------------------------------------------------------------------------

# Item 5.1: fallback labels used when runtime._current_tool_status is not set.
_STATUS_MESSAGES = {
    "get_node_context": "Lendo contexto do nó...",
    "get_selected_nodes_context": "Lendo nós selecionados...",
    "get_active_frame_context": "Lendo frame ativo...",
    "get_local_subgraph_context": "Lendo subgrafo...",
    "get_scene_summary": "Lendo cena...",
    "get_gn_hosts": "Listando objetos GN...",
    "get_tree_parameters": "Lendo parâmetros da árvore...",
    "get_changes_since_last_turn": "Verificando mudanças...",
    "find_tree_nodes": "Buscando nós...",
    "list_tree_nodes": "Listando nós...",
    "resolve_gn_workspace": "Resolvendo workspace GN...",
    "build_tree_structural_memory": "Lendo árvore GN...",
    "read_script_draft": "Lendo draft...",
    "write_script_draft": "Escrevendo draft...",
    "prepare_draft_context": "Preparando contexto de draft...",
    "classify_tree_phases": "Classificando fases da árvore...",
    "map_clinical_parameter_roles": "Mapeando parâmetros clínicos...",
    "interpret_orthosis_tree_logic": "Interpretando lógica da órtese...",
    "analyze_gn_state": "Analisando estado GN...",
    "analyze_scene": "Analisando cena...",
    "capture_screenshot": "Capturando viewport...",
    "query_node_types": "Consultando tipos de nó...",
}


def _run_chat_turn(
    user_text: str,
    api_key: str,
    model: str,
    blend_path: str = "",
    screenshot_pngs: list[bytes] | None = None,
    file_context_blocks: list[dict[str, str]] | None = None,
) -> None:
    """Run in a background thread.  Calls AgentRuntime.run_turn()."""
    try:
        import anthropic as _anthropic
        runtime = _runtime._runtime
        if runtime is None:
            raise RuntimeError("Runtime not initialized on main thread.")
        runtime.client = _anthropic.Anthropic(api_key=api_key)
        runtime.model = model

        def _on_tool_call(tool_name: str, step: int) -> None:
            # Prefer the Portuguese status set by core.agent_loop (includes round
            # info); fall back to _STATUS_MESSAGES for callers that bypass the loop.
            status = getattr(runtime, "_current_tool_status", "") or ""
            if not status:
                status = _STATUS_MESSAGES.get(tool_name, f"{tool_name}...")
            with SESSION._lock:
                SESSION.current_tool = status
                SESSION.tool_call_count = step
            _runtime._schedule_redraw()

        def _on_text_chunk(chunk: str) -> None:
            SESSION.append_stream_chunk(chunk)
            _runtime._schedule_redraw()

        runtime.on_tool_call = _on_tool_call
        runtime.on_text_chunk = _on_text_chunk

        with SESSION._lock:
            SESSION.current_tool = "Starting..."
        _runtime._schedule_redraw()

        image_blocks = None
        if screenshot_pngs:
            image_blocks = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(png).decode("ascii"),
                    },
                }
                for png in screenshot_pngs
            ]

        response_text = runtime.run_turn(
            user_text,
            blend_path=blend_path,
            image_blocks=image_blocks,
            attachment_text_blocks=file_context_blocks,
        )

        SESSION.current_tool = ""
        SESSION.streaming_text = ""
        SESSION.error = ""
        SESSION.add("assistant", response_text)
        _runtime._last_chat_turn_failed = False
        try:
            in_tok, out_tok = runtime.journal.get_last_turn_tokens()
            with SESSION._lock:
                SESSION.last_turn_input_tokens = in_tok
                SESSION.last_turn_output_tokens = out_tok
                SESSION.session_input_tokens += in_tok
                SESSION.session_output_tokens += out_tok
        except Exception:
            pass
        SESSION.running = False
        _runtime._schedule_redraw()

    except Exception as exc:
        SESSION.current_tool = ""
        SESSION.streaming_text = ""
        SESSION.error = str(exc)
        SESSION.add("assistant", f"[Error] {exc}")
        _runtime._last_chat_turn_failed = True
        SESSION.running = False
        _runtime._schedule_redraw()


def _send_user_message(context, user_text: str, *, display_text: str | None = None) -> tuple[set[str], str]:
    scene = context.scene
    text = str(user_text or "")
    if not text.strip():
        return {"CANCELLED"}, "Empty message."

    api_key = _runtime._get_api_key()
    if not api_key:
        return {"CANCELLED"}, "No API key. Set it in Edit > Preferences > Add-ons > Orthosis AI Agent."

    if SESSION.running:
        return {"CANCELLED"}, "Already processing a message."

    # Enable disk-history hydration from this point forward.  The panel starts
    # with hydration disabled so no ghost history appears on open; enabling it
    # here means the UI will start syncing new messages from the store as turns
    # complete and the legacy state is written back to disk.
    _runtime._history_hydration_enabled = True

    blend_path = _runtime._get_effective_blend_path()

    if SESSION.screenshot_running:
        return {"CANCELLED"}, "Wait for screenshot capture to finish before sending."

    screenshot_pngs = SESSION.consume_screenshots()
    file_attachments = SESSION.consume_file_attachments()
    SESSION.set_screenshot_notice("")
    file_context_blocks = _build_file_context_blocks(file_attachments)

    show_text = display_text if isinstance(display_text, str) and display_text.strip() else text.strip()
    if screenshot_pngs:
        count = len(screenshot_pngs)
        suffix = "screenshot" if count == 1 else "screenshots"
        show_text += f"  [+ {count} {suffix}]"
    if file_attachments:
        count = len(file_attachments)
        suffix = "file" if count == 1 else "files"
        show_text += f"  [+ {count} {suffix}]"

    SESSION.add("user", show_text)
    SESSION.running = True
    _runtime._last_chat_turn_failed = False
    SESSION.reset_turn()
    scene.chat_input = ""

    model = _runtime._get_model()
    thread = threading.Thread(
        target=_run_chat_turn,
        args=(text, api_key, model, blend_path, screenshot_pngs, file_context_blocks),
        daemon=True,
    )
    thread.start()
    return {"FINISHED"}, ""


# ---------------------------------------------------------------------------
