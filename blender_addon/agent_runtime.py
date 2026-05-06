"""Agent runtime for chat/API orchestration inside Blender."""

from __future__ import annotations

import json
import os
import time
from copy import deepcopy
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

from .project_paths import resolve_project_root
from .runtime_planning import (
    FOCAL_READ_TOOLS,
    build_structural_index_entry,
    extract_node_name,
    extract_tree_name,
)
from .runtime_agent_loop import agent_loop, send_screenshot_turn
from .runtime_api_client import (
    extract_text,
    is_transient_api_error,
    request_text_with_retry,
    request_with_retry,
    stream_with_retry,
)
from .runtime import state_ops
from .runtime.gn_targeting import canonicalize_gn_tool_input
from .tools import TOOLS, AGENT_TOOLS, dispatch_tool_raw


BASE_SYSTEM_PROMPT = """\
You are Agent 1, a Geometry Nodes copilot inside Blender for orthosis workflows.

Core stance:
- Speak naturally in Brazilian Portuguese. Be concise.
- Every API call costs money and time. Minimize them aggressively.
- Blender Text Editor drafts are the source of truth for generated Python.
- The chat panel is conversational/status UI only; never dump full scripts there.
- The user manually runs drafts from Blender. Never autoexecute draft code.
- On execution feedback, revise the draft before any retry.
"""



_MAX_RETRIES = 2
_RETRY_WAIT_SECONDS = [4, 10]
_BLOCKED_PRODUCT_TOOLS = {
    "make_plan",
    "execute_code",
    "apply_simulator_payload",
    "rename_object",
    "move_to_collection",
}
_DRAFT_BROAD_READ_TOOLS = {
    "get_scene_summary",
    "get_gn_hosts",
    "prepare_draft_context",
    "resolve_gn_workspace",
    "build_tree_structural_memory",
    "list_tree_nodes",
    "get_tree_parameters",
}
_DRAFT_FOCAL_READ_TOOLS = {
    "get_node_context",
    "get_selected_nodes_context",
    "get_active_frame_context",
    "get_local_subgraph_context",
    "find_tree_nodes",
    "get_changes_since_last_turn",
}


@dataclass
class DraftAttemptContract:
    require_read_before_write: bool = True
    allow_write_when_source_missing: bool = False
    require_target_tree_for_write: bool = False
    require_structural_memory_for_write: bool = False
    require_context_evidence_for_write: bool = False
    require_prepared_context_for_write: bool = False
    block_when_prepared_context_has_blockers: bool = False


@dataclass
class DraftAttemptState:
    source_read_attempted: bool = False
    source_read_succeeded: bool = False
    source_block_missing: bool = False
    target_tree: str = ""
    target_resolved: bool = False
    structural_memory_ready: bool = False
    evidence_reads: int = 0
    prepared_context_read: bool = False
    prepared_context_blockers: list[str] = field(default_factory=list)
    write_attempted: bool = False
    write_succeeded: bool = False
    last_block_reason: str = ""

# ---------------------------------------------------------------------------
# Phase 1 of REFATOR_PLAN.md — structured session schema (v1).
#
# The new ``blender_addon.session`` subpackage introduces a structured Session
# schema that will replace the legacy flat dict in later phases. In Phase 2 the
# shared ``Runtime`` mirrors operational saves into Session v1.
USE_STRUCTURED_SESSION_V1 = bool(int(os.environ.get("ORTHOSIS_USE_STRUCTURED_SESSION_V1", "0") or "0"))

# Knowledge updater calls claude-haiku-4-5 on every successful GN turn to
# synthesize reusable patterns.  Useful for corpus growth but adds ~300-500
# invisible tokens of API spend per turn.  Disabled by default in Wave 1 to
# eliminate silent cost.  Set ORTHOSIS_KNOWLEDGE_UPDATER_ENABLED=1 to re-enable.
_KNOWLEDGE_UPDATER_ENABLED = bool(
    int(os.environ.get("ORTHOSIS_KNOWLEDGE_UPDATER_ENABLED", "0") or "0")
)


def load_structured_session_v1(project_root: "Path", blend_path: str = ""):
    """Phase 1 helper: load a v1 ``Session`` for ``blend_path``.

    Imported lazily so that turning the feature off has zero import cost on
    the live runtime path. Returns a ``Session`` object from
    ``blender_addon.session``.
    """
    from .session import SessionV1Store

    return SessionV1Store(project_root=project_root).load(blend_path)



def _resolve_runtime_project_root(project_root: str | Path) -> Path:
    """Best-effort project root resolution for runtime knowledge availability."""
    try:
        candidate = Path(project_root).resolve()
        resolved = resolve_project_root()
        if candidate == resolved:
            return candidate
    except Exception:
        pass
    return resolve_project_root()


def _make_history_summariser(runtime: Any) -> Any:
    """Return a SummariserCallback that compresses evicted history via Haiku.

    Fires only when ``BoundedHistory`` overflows (>80 messages).  Uses the
    lightweight LIGHT_MODEL so the cost is minimal (~300 output tokens, once
    every ~40 turns in very long sessions).  Any exception is silently caught
    by ``BoundedHistory._enforce_bound`` — a failing summariser never breaks
    history writes.
    """
    from .model_policy import LIGHT_MODEL

    def _summarise(evicted: list[Any], older_summary: str | None) -> str | None:
        if not evicted:
            return older_summary
        try:
            prior = f"\nContexto anterior resumido:\n{older_summary}" if older_summary else ""
            msgs_text = "\n".join(
                f"{m.role}: {m.content[:400]}" for m in evicted
            )
            prompt = (
                f"Resumo da conversa anterior (Blender Geometry Nodes copiloto):{prior}\n\n"
                f"Mensagens a condensar:\n{msgs_text}"
            )
            response = runtime.client.messages.create(
                model=LIGHT_MODEL,
                system=(
                    "Faça um resumo conciso em 3-5 bullets em português. "
                    "Preserve nomes de nós, valores numéricos e operações executadas. "
                    "Sem introdução, apenas os bullets."
                ),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
            )
            text = "".join(
                block.text
                for block in response.content
                if getattr(block, "type", "") == "text"
            )
            return text.strip() or older_summary
        except Exception:
            return older_summary

    return _summarise


class AgentRuntime:
    """Single-turn agent loop with dynamic context composition."""

    def __init__(
        self,
        project_root: str | Path,
        api_key: str,
        model: str = "claude-sonnet-4-6",
        runtime: Any | None = None,
    ):
        if runtime is None:
            from .runtime import Runtime

            resolved_project_root = _resolve_runtime_project_root(project_root)
            runtime = Runtime(project_root=resolved_project_root)
        self.runtime = runtime
        self.project_root = Path(getattr(runtime, "project_root", _resolve_runtime_project_root(project_root)))
        self.knowledge_domain_dir = self.project_root / "knowledge" / "domain"
        self.knowledge_skill_dir = self.project_root / "knowledge" / "skills"

        self.journal = self.runtime.journal
        self.dispatcher = self.runtime.dispatcher
        # Use AGENT_TOOLS (subset): excludes forbidden/superseded tools to reduce
        # schema noise sent to the API on every turn (~1200-2500 tokens saved).
        self.tools = AGENT_TOOLS
        self.model = model

        import anthropic

        self.client = anthropic.Anthropic(api_key=api_key)
        self._messages: list[dict[str, Any]] = []
        self._session_state: dict[str, Any] = {}
        self.on_tool_call = None   # callback(tool_name: str, step: int)
        self.on_text_chunk = None  # callback(chunk: str) → None; enables streaming
        self._tool_step = 0
        self._read_call_counts: dict[str, int] = {}
        self._current_turn_tools: list[dict[str, Any]] = []
        self._session_memory: dict[str, Any] = {}
        self._structural_index: dict[str, Any] = {}
        self._local_scope: dict[str, Any] = {}
        self._halt_execution: bool = False
        self._halt_message: str = ""
        self._active_backend_session_id: str = ""
        # Current turn's v1 session (in-memory). Set by run_turn at turn start.
        # _execute_tool reads phase from this instead of reloading from disk,
        # so phase transitions made mid-turn (e.g. confirm → executing) are
        # immediately visible to the phase gate.
        self._active_v1_session: Any = None
        self._canonical_gn_target: dict[str, Any] | None = None
        self._canonical_gn_target_source: str = ""
        self._session_memory_usage_reasons: set[str] = set()
        self._draft_tool_policy: dict[str, Any] = {}
        self._draft_attempt_state: DraftAttemptState | None = None
        self._last_agent_loop_truncated: bool = False
        self._last_agent_loop_round_limit_hit: bool = False
        # Item 5.1: Portuguese status text updated before each tool call.
        # Read by the panel callback to display dynamic progress.
        self._current_tool_status: str = ""
        # Item 5.4: set to True when write_script_draft succeeds this turn.
        # Triggers work_cycle_phase → pending_user_execution before save.
        self._draft_written_this_turn: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_turn(
        self,
        user_message: str,
        blend_path: str = "",
        image_blocks: list[dict[str, Any]] | None = None,
        attachment_text_blocks: list[dict[str, Any]] | None = None,
    ) -> str:
        """Draft-first turn entry point: route via TurnRouter, then handler."""
        from .runtime.router import TurnRouter
        from .runtime.handlers import TurnContext, dispatch_turn

        # --- Per-turn reset ---
        self._tool_step = 0
        self._halt_execution = False
        self._halt_message = ""
        self._current_turn_tools = []
        self._read_call_counts = {}
        self._canonical_gn_target = None
        self._canonical_gn_target_source = ""
        self._session_memory_usage_reasons = set()
        self._draft_tool_policy = {}
        self._draft_attempt_state = None
        self._last_agent_loop_truncated = False
        self._last_agent_loop_round_limit_hit = False
        self._current_tool_status = ""
        self._draft_written_this_turn = False

        # --- Load v1 session (single fixed session file) ---
        session = self.runtime.v1_session_for(blend_path)

        # Update focus.blend_path if not yet set (first turn after fresh install).
        if blend_path and not getattr(getattr(session, "focus", None), "blend_path", ""):
            try:
                focus = session.focus
                session.update_focus(
                    blend_path=blend_path,
                    object_name=getattr(focus, "object_name", None),
                    modifier_name=getattr(focus, "modifier_name", None),
                    tree_name=getattr(focus, "tree_name", None),
                )
                self.runtime.save_v1_session(session)
            except Exception:
                pass

        # Cache in-memory for _active_v1_session phase checks — avoids stale disk reads.
        self._active_v1_session = session

        # Onda 3: hydrate session_state from the persisted store (source of truth).
        # The V1 JSON also mirrors the field, but the dedicated file is more
        # authoritative — it is updated atomically at every turn end.
        try:
            _sid_hydrate = getattr(getattr(session, "identity", None), "session_id", "") or ""
            _persisted_state = self.runtime.read_persisted_session_state(_sid_hydrate)
            if _persisted_state:
                session.execution_state.session_state = _persisted_state
            _pending = getattr(session.execution_state, "pending_user_decision", None)
            if _pending is not None and str(getattr(_pending, "status", "") or "") == "pending":
                session.execution_state.session_state = "STRATEGY_PROPOSED"
        except Exception:
            pass
        try:
            _sid_run = getattr(getattr(session, "identity", None), "session_id", "") or ""
            self.journal.start_run(session_id=_sid_run, blend_file=blend_path or "")
        except Exception as _run_exc:
            try:
                self.journal.log_runtime_event(
                    event_type="journal_run_start_error",
                    payload={"error": str(_run_exc)},
                    status="warning",
                )
            except Exception:
                pass

        # Make user-provided context auditable. Screenshots/files are consumed
        # by the UI before run_turn(), so the journal is the only reliable
        # place to prove they reached the runtime layer.
        try:
            _image_count = len(image_blocks or [])
            _attachment_text_count = len(attachment_text_blocks or [])
            if str(user_message or "").strip():
                self.journal.log_runtime_event(
                    event_type="context_provided_by_user_text",
                    payload={"chars": len(str(user_message or ""))},
                )
            if _image_count:
                self.journal.log_runtime_event(
                    event_type="context_provided_by_user_screenshot",
                    payload={"image_blocks_count": _image_count},
                )
            if _attachment_text_count:
                self.journal.log_runtime_event(
                    event_type="context_provided_by_user_attachment",
                    payload={"attachment_text_blocks_count": _attachment_text_count},
                )
        except Exception:
            pass

        # --- Restore in-memory message buffer from persisted history on resume ---
        # If _messages is empty (fresh Blender start / first turn) but the session
        # already has saved history, populate the buffer so the agent has context
        # from previous sessions. Keeps last 12 messages (≈ 6 complete turns).
        if not self._messages:
            try:
                saved_msgs = list(getattr(session.history, "messages", []))
                if saved_msgs:
                    for _hm in saved_msgs[-12:]:
                        _role = getattr(_hm, "role", "")
                        _text = getattr(_hm, "content", "")
                        if _role and _text:
                            self._messages.append({"role": _role, "content": _text})
            except Exception as _hist_exc:
                try:
                    self.journal.log_runtime_event(
                        event_type="history_resume_error",
                        payload={"error": str(_hist_exc)},
                        status="warning",
                    )
                except Exception:
                    pass

        # --- Load flat runtime state only as an operational shim for tool execution ---
        runtime_state = self.runtime.load_runtime_state(blend_path)
        op_state = getattr(session, "operational_state", None)
        if op_state is not None:
            for _key in ("tree_structural_memory", "tree_change_markers", "local_scope", "structural_index"):
                _value = getattr(op_state, _key, None)
                if isinstance(_value, dict) and _value and not runtime_state.get(_key):
                    runtime_state[_key] = dict(_value)
        session_memory = state_ops.get_session_memory(runtime_state)
        focus = getattr(session, "focus", None)
        focus_tree = str(getattr(focus, "tree_name", "") or "").strip()
        runtime_state["last_target_tree"] = focus_tree
        if not isinstance(session_memory, dict):
            session_memory = {}
        if focus_tree:
            session_memory["target_tree"] = focus_tree
        else:
            session_memory.pop("target_tree", None)
        runtime_state["session_memory"] = session_memory

        self._session_state = runtime_state
        self._session_memory = session_memory
        self._structural_index = dict(self._session_state.get("structural_index") or {})
        self._local_scope = dict(self._session_state.get("local_scope") or {})
        if bool(runtime_state.get("simulate_bridge_failure", False)):
            try:
                self.journal.log_runtime_event(
                    event_type="simulate_bridge_failure_active",
                    payload={"enabled": True, "blend_path": blend_path or ""},
                    status="warning",
                )
            except Exception:
                pass

        # --- W3-T2: validate session_memory GN fields against live bpy ---
        # Runs BEFORE fast-path and before build_system_prompt so the model
        # never receives stale target_tree / relevant_nodes in its context.
        # Mutations synced onto session.operational_state.session_memory so
        # end-of-turn save_v1_session() persists cleanup without extra save.
        try:
            _sm_warnings = state_ops.validate_session_memory_gn(runtime_state)
            if _sm_warnings:
                _clean_memory = dict(runtime_state.get("session_memory") or {})
                try:
                    session.operational_state.session_memory = _clean_memory
                    self._session_memory = _clean_memory
                except Exception:
                    pass
                for _w in _sm_warnings:
                    try:
                        self.journal.log_runtime_event(
                            event_type="session_memory_stale_cleared",
                            payload={"warning": _w},
                            status="warning",
                        )
                    except Exception:
                        pass
        except Exception as _smv_exc:
            try:
                self.journal.log_runtime_event(
                    event_type="session_memory_validation_error",
                    payload={"error": str(_smv_exc)},
                    status="warning",
                )
            except Exception:
                pass

        # Legacy purge: "awaiting_confirmation" was removed from EXECUTION_PHASES
        # in Onda 1F-B and pending_mutation removed from ExecutionState in Onda 1F-C.
        # Sessions loaded from disk before __post_init__ normalises may still carry
        # the phase as a raw string; normalise here before routing.
        es = getattr(session, "execution_state", None)
        if es is not None and str(getattr(es, "phase", "") or "") == "awaiting_confirmation":
            try:
                es.set_phase("drafting" if getattr(es, "current_draft", None) is not None else "idle")
                self.journal.log_runtime_event(
                    event_type="legacy_awaiting_confirmation_purged",
                    payload={"source": "agent_runtime_purge"},
                    status="warning",
                )
            except Exception:
                pass

        pending_resolution = None
        try:
            from .runtime.pending_decision import (
                clarification_response as _pending_clarification_response,
                resolve_pending_decision as _resolve_pending_decision,
            )
            pending_resolution = _resolve_pending_decision(session, user_message, runtime=self)
            if bool(getattr(pending_resolution, "needs_clarification", False)):
                _clarify_text = _pending_clarification_response(session)
                self._messages.append({"role": "user", "content": user_message})
                self._messages.append({"role": "assistant", "content": _clarify_text})
                _sid_clarify = getattr(getattr(session, "identity", None), "session_id", None) or ""
                if _sid_clarify:
                    try:
                        self.runtime.append_chat_message(_sid_clarify, role="user", content=user_message, turn_class="pending_decision")
                        self.runtime.append_chat_message(_sid_clarify, role="assistant", content=_clarify_text, turn_class="pending_decision")
                    except Exception:
                        pass
                    try:
                        from .session import compute_next_state as _pd_compute_next_state
                        _prev_pd_state = str(getattr(session.execution_state, "session_state", "") or "IDLE")
                        _next_pd_state = _pd_compute_next_state(session)
                        session.execution_state.session_state = _next_pd_state
                        self.runtime.persist_session_state(
                            _sid_clarify,
                            next_state=_next_pd_state,
                            previous_state=_prev_pd_state,
                            blend_path=blend_path or "",
                        )
                    except Exception:
                        pass
                try:
                    self.runtime.save_v1_session(session)
                except Exception:
                    pass
                return _clarify_text
        except Exception as _pd_exc:
            try:
                self.journal.log_runtime_event(
                    event_type="pending_decision_resolution_error",
                    payload={"error": str(_pd_exc)},
                    status="warning",
                )
            except Exception:
                pass

        # --- Fast path: deterministic resolution without LLM ---
        # Intercepts greetings, help, and simple reads
        # before the TurnRouter.  Returns immediately when handled; falls through
        # silently on any exception so the normal flow is never blocked.
        # (The "awaiting_confirmation" phase guard that was here was removed in
        # Onda 1F-B — the purge block above ensures phase is always valid here.)
        try:
            from .fast_path import try_fast_path
            _fp_result = try_fast_path(user_message, session=session, runtime=self)
        except Exception:
            _fp_result = None
        if _fp_result is not None:
            _fast_text, _fp_meta = _fp_result
            # Minimal post-processing: mirror exchange into in-memory buffer,
            # JSONL chat store, and in-memory session history.
            self._messages.append({"role": "user",      "content": user_message})
            self._messages.append({"role": "assistant", "content": _fast_text})
            _fp_sid = getattr(getattr(session, "identity", None), "session_id", None) or ""
            if _fp_sid:
                try:
                    self.runtime.append_chat_message(_fp_sid, role="user", content=user_message, turn_class="fast_path")
                    self.runtime.append_chat_message(_fp_sid, role="assistant", content=_fast_text, turn_class="fast_path")
                except Exception:
                    pass
            try:
                from .session.history import BoundedHistory
                _bh = BoundedHistory(session.history)
                _bh.append(role="user",      content=user_message, turn_class="fast_path")
                _bh.append(role="assistant", content=_fast_text,   turn_class="fast_path")
            except Exception:
                pass
            runtime_state["turn_counter"] = (
                int(runtime_state.get("turn_counter") or 0) + 1
            )
            # Onda 3: refresh persisted session_state on fast-path turns too.
            try:
                from .session import compute_next_state as _fp_compute_next_state
                _fp_prev = str(getattr(session.execution_state, "session_state", "") or "IDLE")
                _fp_next = _fp_compute_next_state(session)
                session.execution_state.session_state = _fp_next
                if _fp_sid:
                    self.runtime.persist_session_state(
                        _fp_sid,
                        next_state=_fp_next,
                        previous_state=_fp_prev,
                        blend_path=blend_path or "",
                    )
            except Exception:
                pass
            try:
                self.runtime.save_v1_session(session)
            except Exception:
                pass
            try:
                self.journal.log_runtime_event(
                    event_type="fast_path_hit",
                    payload={"message_preview": user_message[:80], **_fp_meta},
                )
                if _fp_meta.get("fp_type") == "draft_confirmation":
                    self.journal.log_runtime_event(
                        event_type="draft_confirmation_short_circuit",
                        payload={
                            "block_name": _fp_meta.get("block_name", ""),
                            "version": _fp_meta.get("version", 0),
                            "message_preview": user_message[:80],
                        },
                    )
            except Exception:
                pass
            return _fast_text

        # --- Handle awaiting_confirmation override ---
        # The router still detects "awaiting_confirmation" as a legacy string
        # and emits "legacy_awaiting_confirmation_purged" signal; clear state.
        _router = TurnRouter()
        turn_class, meta = _router.classify(session, user_message)
        _pending_after_resolution = getattr(session.execution_state, "pending_user_decision", None)
        _pending_write_approval = (
            pending_resolution is not None
            and str(getattr(pending_resolution, "status", "") or "") == "answered"
            and str(getattr(_pending_after_resolution, "kind", "") or "") in {"strategy_choice", "repair_direction", "write_confirmation"}
        )
        if _pending_write_approval:
            try:
                from .runtime.router import TurnClass as _TurnClass
                turn_class = _TurnClass.DRAFT_WORKSPACE
                meta.turn_class = turn_class
                meta.turn_intent = "strategy_approval"
                meta.session_state = "STRATEGY_APPROVED"
                meta.goal_mode = "focal_correction"
                if "pending_decision_resolved" not in meta.signals:
                    meta.signals.append("pending_decision_resolved")
                _kind_log = str(getattr(_pending_after_resolution, "kind", "") or "")
                _answered_log = str(getattr(pending_resolution, "answered_with", "") or "")
                self.journal.log_runtime_event(
                    event_type="pending_write_approval_short_circuit",
                    payload={
                        "kind": _kind_log,
                        "answered_with": _answered_log,
                        "forced_goal_mode": "focal_correction",
                        "forced_turn_intent": "strategy_approval",
                    },
                )
            except Exception:
                pass

        if "legacy_awaiting_confirmation_purged" in meta.signals:
            try:
                session.execution_state.set_phase(
                    "drafting" if getattr(session.execution_state, "current_draft", None) is not None else "idle"
                )
            except Exception:
                pass
            turn_class, meta = _router.classify(session, user_message)
            if _pending_write_approval:
                try:
                    from .runtime.router import TurnClass as _TurnClass
                    turn_class = _TurnClass.DRAFT_WORKSPACE
                    meta.turn_class = turn_class
                    meta.turn_intent = "strategy_approval"
                    meta.session_state = "STRATEGY_APPROVED"
                    meta.goal_mode = "focal_correction"
                    if "pending_decision_resolved" not in meta.signals:
                        meta.signals.append("pending_decision_resolved")
                except Exception:
                    pass

        # --- Routing observability log (read-only; no dispatch impact) ---
        try:
            from .runtime.routing_obs import compute_shadow_handler
            _shadow = compute_shadow_handler(
                turn_intent=str(getattr(meta, "turn_intent", "") or ""),
                session_state=str(getattr(meta, "session_state", "") or ""),
                chosen_class=str(turn_class.value),
            )
            _diverges = _shadow != str(turn_class.value)
            self.journal.log_runtime_event(
                event_type="routing_observation",
                payload={
                    "message_preview": user_message[:120],
                    "turn_class": str(turn_class.value),
                    "turn_intent": str(getattr(meta, "turn_intent", "") or ""),
                    "session_state": str(getattr(meta, "session_state", "") or ""),
                    "handler_chosen": str(turn_class.value),
                    "handler_by_capability": _shadow,
                    "diverges": _diverges,
                    "signals": list(getattr(meta, "signals", []) or []),
                    "confidence": str(getattr(meta, "confidence", "") or ""),
                },
            )
        except Exception:
            pass

        self._refresh_conversational_session_memory(
            runtime_state,
            session,
            user_message,
            str(turn_class.value),
        )

        # --- Build context ---
        ctx = TurnContext(
            session=session,
            message=user_message,
            meta=meta,
            blend_path=blend_path,
            image_blocks=list(image_blocks or []),
            attachment_text_blocks=list(attachment_text_blocks or []),
            _runtime=self,
            knowledge_dir=self.knowledge_domain_dir,
        )

        # --- Select model for this turn (Wave 2B routing) ---
        # Temporarily override self.model so every API call made by the handler
        # (via _agent_loop or _request_text_response) uses the turn-appropriate
        # model.  Restored unconditionally in the finally block.
        from .model_policy import select_model as _select_model, select_max_tokens as _select_max_tokens
        _turn_model = _select_model(str(turn_class.value), self.model, user_message)
        _turn_max_tokens = _select_max_tokens(str(turn_class.value))
        _saved_model = self.model
        self.model = _turn_model
        try:
            self.journal.log_runtime_event(
                event_type="turn_model_selected",
                payload={
                    "turn_class": str(turn_class.value),
                    "model": _turn_model,
                    "default_model": _saved_model,
                    "max_tokens": _turn_max_tokens,
                },
            )
        except Exception:
            pass

        # --- Dispatch ---
        try:
            _messages_len_before_dispatch = len(self._messages)
            result = dispatch_turn(turn_class, ctx)
        finally:
            # Always restore the original model, even if dispatch raises.
            self.model = _saved_model

        # The agent loop may append turn-internal assistant drafts to
        # ``_messages`` while tools are still running. Keep only the canonical
        # user/final-assistant exchange in the cross-turn buffer; otherwise a
        # stale diagnostic can leak into the next turn and appear twice in UI.
        try:
            if isinstance(self._messages, list):
                self._messages = self._messages[:_messages_len_before_dispatch]
                self._messages.append({"role": "user", "content": user_message})
                self._messages.append({"role": "assistant", "content": result.response_text})
        except Exception:
            pass

        # --- Persist chat to JSONL immediately (before V1 save) ---
        _tc = str(getattr(meta, "turn_class", "") or "")
        _session_id = getattr(getattr(session, "identity", None), "session_id", None) or ""
        if _session_id:
            try:
                self.runtime.append_chat_message(_session_id, role="user", content=user_message, turn_class=_tc)
                self.runtime.append_chat_message(_session_id, role="assistant", content=result.response_text, turn_class=_tc)
            except Exception as _chat_exc:
                try:
                    self.journal.log_runtime_event(
                        event_type="chat_jsonl_write_error",
                        payload={"error": str(_chat_exc)},
                        status="warning",
                    )
                except Exception:
                    pass

        # --- Update in-memory session history (for agent context) ---
        try:
            from .session.history import BoundedHistory
            bh = BoundedHistory(session.history, summariser=_make_history_summariser(self))
            bh.append(role="user", content=user_message, turn_class=_tc)
            bh.append(role="assistant", content=result.response_text, turn_class=_tc)
        except Exception as _hist_save_exc:
            try:
                self.journal.log_runtime_event(
                    event_type="history_append_error",
                    payload={"error": str(_hist_save_exc)},
                    status="warning",
                )
            except Exception:
                pass

        # --- Bump turn counter on legacy state ---
        runtime_state["turn_counter"] = int(runtime_state.get("turn_counter") or 0) + 1

        # --- Onda 3: compute & persist next session_state ---
        # Runs before save_v1_session so the V1 JSON mirrors the dedicated file.
        try:
            from .session import compute_next_state as _compute_next_state
            _prev_state = str(getattr(session.execution_state, "session_state", "") or "IDLE")
            _pending = getattr(session.execution_state, "pending_user_decision", None)
            _pending_status = str(getattr(_pending, "status", "") or "") if _pending is not None else ""
            _next_state = _compute_next_state(session)
            if (
                _prev_state == "STRATEGY_PROPOSED"
                and _pending_status == "pending"
                and bool(getattr(session.execution_state, "retry_requires_draft_change", False))
                and _next_state == "STRATEGY_PROPOSED"
            ):
                try:
                    self.journal.log_runtime_event(
                        event_type="state_transition_blocked",
                        payload={
                            "previous_state": _prev_state,
                            "blocked_next_state": "REPAIRING",
                            "reason": "pending_user_decision",
                        },
                        status="info",
                    )
                except Exception:
                    pass
            session.execution_state.session_state = _next_state
            _sid_persist = getattr(getattr(session, "identity", None), "session_id", "") or ""
            if _sid_persist:
                self.runtime.persist_session_state(
                    _sid_persist,
                    next_state=_next_state,
                    previous_state=_prev_state,
                    blend_path=blend_path or "",
                )
        except Exception as _ss_exc:
            try:
                self.journal.log_runtime_event(
                    event_type="session_state_compute_error",
                    payload={"error": str(_ss_exc)},
                    status="warning",
                )
            except Exception:
                pass

        # --- Onda 5 (Item 5.4): PRONTO after draft write ---
        if getattr(self, "_draft_written_this_turn", False):
            try:
                session.execution_state.set_work_cycle_phase("pending_user_execution")
            except Exception:
                pass

        # --- Save v1 session (now primary) ---
        try:
            self._sync_operational_state_to_session(session, runtime_state)
            self.runtime.save_v1_session(session)
        except Exception as _save_exc:
            try:
                self.journal.log_runtime_event(
                    event_type="v1_session_save_error",
                    payload={"error": str(_save_exc)},
                    status="error",
                )
            except Exception:
                pass

        # --- Knowledge extraction (background, disabled by default) ---
        # Enable with: ORTHOSIS_KNOWLEDGE_UPDATER_ENABLED=1
        if _KNOWLEDGE_UPDATER_ENABLED:
            try:
                from .knowledge_updater import maybe_extract_knowledge
                maybe_extract_knowledge(
                    journal_session_file=self.journal.session_file,
                    goal_id=self.journal._current_goal_id or "",
                    had_errors=bool(getattr(result, "phase_transition", None) == "failed"),
                    api_key=self.client.api_key,
                    knowledge_dir=self.knowledge_domain_dir,
                    client=self.client,
                )
            except Exception as _ke:
                try:
                    self.journal.log_runtime_event(
                        event_type="knowledge_extraction_error",
                        payload={"error": str(_ke)},
                        status="warning",
                    )
                except Exception:
                    pass

        return result.response_text

    @staticmethod
    def _sync_operational_state_to_session(session: Any, runtime_state: dict[str, Any]) -> None:
        op = getattr(session, "operational_state", None)
        if op is None or not isinstance(runtime_state, dict):
            return
        for key in (
            "session_memory",
            "local_scope",
            "structural_index",
            "tree_structural_memory",
            "tree_change_markers",
            "last_scene_summary",
            "last_gn_summary",
        ):
            value = runtime_state.get(key)
            if isinstance(value, dict):
                setattr(op, key, dict(value))
        for key in ("recent_actions", "risky_events"):
            value = runtime_state.get(key)
            if isinstance(value, list):
                setattr(op, key, [dict(item) for item in value if isinstance(item, dict)])
        try:
            op.turn_counter = int(runtime_state.get("turn_counter") or 0)
        except Exception:
            pass

    def _refresh_conversational_session_memory(
        self,
        runtime_state: dict[str, Any],
        session: Any,
        user_message: str,
        turn_class: str,
    ) -> None:
        if turn_class in {"trivial_chat", "state_control"}:
            return
        memory = state_ops.get_session_memory(runtime_state)
        if not isinstance(memory, dict):
            return

        text = str(user_message or "").strip()
        lowered = text.lower()
        existing_goal = str(memory.get("last_goal") or "").strip()
        existing_hypothesis = str(memory.get("last_hypothesis") or "").strip()

        domain_terms = (
            "ortese", "ortese", "órtese", "biomodelo", "palma",
            "metacarpo", "metacarpos", "mao", "mão", "gn", "geometry nodes",
        )
        failure_terms = (
            "falhou", "falha", "erro", "errado", "nao funcionou",
            "não funcionou", "nada aconteceu", "sem efeito",
        )
        correction_terms = (
            "corrige", "corrigir", "arruma", "ajusta", "ajustar",
            "conserta", "reescreve", "draft",
        )

        updates: dict[str, Any] = {}
        has_domain_context = any(term in lowered for term in domain_terms)
        has_failure_context = any(term in lowered for term in failure_terms)
        has_correction_context = any(term in lowered for term in correction_terms)

        es = getattr(session, "execution_state", None)
        draft = getattr(es, "current_draft", None) if es is not None else None
        draft_desc = str(getattr(draft, "description", "") or "").strip()
        draft_tree = str(getattr(draft, "tree_name", "") or getattr(es, "draft_target_tree", "") or "").strip() if es is not None else ""

        if not existing_goal:
            if has_domain_context:
                updates["last_goal"] = (
                    "Desenvolver e corrigir a arvore Geometry Nodes do fluxo de ortese/biomodelo, "
                    "com foco em palma, metacarpos e ajuste procedural."
                )
            elif draft_desc or draft_tree:
                target = f" para a arvore {draft_tree}" if draft_tree else ""
                updates["last_goal"] = f"Corrigir e evoluir o draft Python{target} salvo no Text Editor."

        if not existing_hypothesis:
            if has_failure_context:
                updates["last_hypothesis"] = (
                    "O draft atual precisa ser diagnosticado antes de qualquer nova tentativa manual."
                )
            elif has_domain_context:
                updates["last_hypothesis"] = (
                    "A arvore GN deve preservar o contexto anatomico do biomodelo enquanto ajusta a logica procedural."
                )
            elif has_correction_context and (draft_desc or draft_tree):
                updates["last_hypothesis"] = (
                    "A proxima acao util e ler o draft atual, corrigir a causa provavel e salvar uma revisao completa."
                )

        if not updates:
            return

        previous_memory = dict(memory)
        self._session_memory = state_ops.update_session_memory(runtime_state, updates)
        changed_keys = sorted(
            key for key in updates
            if previous_memory.get(key) != self._session_memory.get(key)
        )
        if not changed_keys:
            return
        try:
            self.journal.log_runtime_event(
                event_type="session_memory_updated",
                payload={
                    "session_memory_updated": True,
                    "source": "conversation_context",
                    "changed_keys": changed_keys,
                    "has_goal": bool(self._session_memory.get("last_goal")),
                    "has_hypothesis": bool(self._session_memory.get("last_hypothesis")),
                    "target_tree": self._session_memory.get("target_tree", ""),
                    "relevant_nodes_count": len(self._session_memory.get("relevant_nodes", [])),
                },
            )
        except Exception:
            pass

    def clear_history(self, blend_path: str = "") -> None:
        self._messages = []
        try:
            session = self._active_v1_session
            if session is None and str(blend_path or "").strip():
                session = self.runtime.v1_session_for(blend_path)
                self._active_v1_session = session
            session_id = getattr(getattr(session, "identity", None), "session_id", None) or ""
            if session_id:
                self.runtime.clear_chat_history(session_id)
            history = getattr(session, "history", None)
            if history is not None and isinstance(getattr(history, "messages", None), list):
                history.messages.clear()
                self.runtime.save_v1_session(session)
        except Exception:
            pass

    def clear_runtime_context(self) -> None:
        """Clear only volatile API context after a .blend reload.

        The visible chat history is persisted in JSONL and must survive
        File > Open/Revert, including snapshot restores. The Clear button uses
        clear_history() when the user intentionally wants to erase it.
        """
        self._messages = []
        self._active_v1_session = None

    # ------------------------------------------------------------------
    # Agent loop
    # ------------------------------------------------------------------

    def _agent_loop(
        self,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        excluded_tools: "frozenset[str] | None" = None,
        max_rounds: int | None = None,
    ) -> str:
        # Hard product cutover: the interactive draft-first runtime never
        # exposes the legacy planning or direct-execution tools to the model.
        product_excluded = set(_BLOCKED_PRODUCT_TOOLS)
        if excluded_tools:
            excluded_tools = frozenset(set(excluded_tools) | product_excluded)
        else:
            excluded_tools = frozenset(product_excluded)
        return agent_loop(
            self, system, messages,
            max_tokens=max_tokens,
            excluded_tools=excluded_tools,
            max_rounds=max_rounds,
        )

    def _request_text_with_retry(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 1400,
    ):
        return request_text_with_retry(
            self,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            max_retries=_MAX_RETRIES,
            retry_wait_seconds=_RETRY_WAIT_SECONDS,
            is_transient_api_error_fn=is_transient_api_error,
        )

    def _request_text_response(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 1400,
        event_type: str = "api_usage",
    ) -> str:
        request_t0 = time.time()
        response = self._request_text_with_retry(
            system=system,
            messages=messages,
            max_tokens=max_tokens,
        )
        elapsed_ms = int((time.time() - request_t0) * 1000)
        usage = getattr(response, "usage", None)
        if usage:
            self.journal.accumulate_tokens(
                getattr(usage, "input_tokens", 0),
                getattr(usage, "output_tokens", 0),
            )
            self.journal.log_runtime_event(
                event_type=event_type,
                payload={
                    "input_tokens": getattr(usage, "input_tokens", 0),
                    "output_tokens": getattr(usage, "output_tokens", 0),
                    "round_time_ms": elapsed_ms,
                    "mode": "text_only",
                    "model": self.model,
                    "max_tokens": max_tokens,
                },
            )
        return self._extract_text(response)

    def _execute_tool(self, tool_name: str, tool_input: dict[str, Any], api_elapsed_ms: int) -> str:
        """Tool dispatch for the draft-first product runtime."""
        if tool_name in _BLOCKED_PRODUCT_TOOLS:
            try:
                self.journal.log_runtime_event(
                    event_type="blocked_product_tool",
                    payload={"tool_name": tool_name},
                    status="blocked",
                )
            except Exception:
                pass
            return f"BLOCKED: {tool_name} is not available in the draft-first product runtime."

        budget_block = self._enforce_draft_tool_policy(tool_name)
        if budget_block:
            tool_record = {
                "name": tool_name,
                "input": dict(tool_input or {}),
                "result": budget_block[:300],
                "status": "blocked",
                "result_payload": {},
            }
            self._current_turn_tools.append(tool_record)
            try:
                self._record_draft_attempt_tool_result(
                    tool_name=tool_name,
                    tool_input=tool_input,
                    runtime_raw={"status": "blocked", "error": budget_block, "result": {}},
                )
            except Exception:
                pass
            return budget_block

        effective_input = self._normalize_tool_input(tool_name, dict(tool_input or {}))
        effective_input, deviation = canonicalize_gn_tool_input(
            tool_name,
            effective_input,
            getattr(self, "_canonical_gn_target", None),
        )
        if deviation is not None:
            self.journal.log_runtime_event(
                event_type="canonical_target_deviation",
                payload=deviation,
                status="blocked",
            )
            return (
                "BLOCKED: this read conflicts with the canonical GN target for this turn. "
                "Ask the user which object/modifier/node group to use before reading a different tree."
            )


        started = time.time()
        state = self._session_state or {}
        if bool(state.get("simulate_bridge_failure", False)) and tool_name == "build_tree_structural_memory":
            runtime_raw = {
                "status": "error",
                "tool_name": tool_name,
                "error": "Simulated bridge failure: debug flag simulate_bridge_failure is enabled.",
            }
            result = self._format_runtime_tool_result(runtime_raw)
            self._postprocess_tool(tool_name, effective_input, runtime_raw, result, 0)
            return result
        if tool_name == "write_script_draft":
            try:
                self.journal.log_runtime_event(
                    event_type="script_draft_write_attempted",
                    payload={
                        "turn_class": str((getattr(self, "_draft_tool_policy", {}) or {}).get("turn_class") or ""),
                        "block_name": str(effective_input.get("block_name") or "GN_Agent_Draft"),
                        "char_count": len(str(effective_input.get("code") or "")),
                    },
                )
            except Exception:
                pass
        runtime_raw = dispatch_tool_raw(
            tool_name,
            effective_input,
            route="product",
            output_mode="compact",
            user_confirmed=True,
            debug_mode=bool(state.get("debug_mode", False)),
            explicit_override_mode=bool(state.get("explicit_override_mode", False)),
            mcp_write_enabled=bool(state.get("mcp_write_enabled", False)),
            blend_path=str(state.get("blend_path", "")),
            journal_session_id=self.journal.session_id,
            journal_run_id=self.journal.run_id,
            journal_goal_id=self.journal.current_goal_id,
        )
        tool_elapsed_ms = int((time.time() - started) * 1000)
        result = self._format_runtime_tool_result(runtime_raw)

        if result.startswith(("ERROR:", "BLOCKED:")) and tool_name in {
            "get_active_frame_context",
            "get_selected_nodes_context",
            "get_local_subgraph_context",
        }:
            result = self._handle_stale_local_scope_tool_failure(tool_name, result)

        if tool_name == "capture_screenshot":
            analyzed = self._send_screenshot_turn(result)
            self.journal.log_runtime_event(
                event_type="visual_evidence_processed",
                payload={"tool_name": tool_name, "result_chars": len(analyzed)},
            )
            return analyzed

        self._postprocess_tool(tool_name, effective_input, runtime_raw, result, tool_elapsed_ms)
        return result

    def _postprocess_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        runtime_raw: dict[str, Any],
        result: str,
        tool_elapsed_ms: int,
    ) -> None:
        """Post-dispatch bookkeeping: journal, turn-tool list, operational state."""
        self._tool_step += 1
        tool_record = {
            "name": tool_name,
            "input": tool_input,
            "result": result[:300],
            "status": str(runtime_raw.get("status", "")),
        }
        if tool_name == "write_script_draft":
            payload = runtime_raw.get("result", {}) if isinstance(runtime_raw, dict) else {}
            tool_record["result_payload"] = dict(payload) if isinstance(payload, dict) else {}
        self._current_turn_tools.append(tool_record)
        try:
            self._record_draft_attempt_tool_result(
                tool_name=tool_name,
                tool_input=tool_input,
                runtime_raw=runtime_raw,
            )
        except Exception as _attempt_exc:
            try:
                self.journal.log_runtime_event(
                    event_type="draft_attempt_state_error",
                    payload={"tool": tool_name, "error": str(_attempt_exc)},
                    status="warning",
                )
            except Exception:
                pass
        try:
            self._update_operational_state_from_tool(
                tool_name=tool_name,
                tool_input=tool_input,
                runtime_raw=runtime_raw,
            )
        except Exception as _state_exc:
            try:
                self.journal.log_runtime_event(
                    event_type="operational_state_update_error",
                    payload={"tool": tool_name, "error": str(_state_exc)},
                    status="warning",
                )
            except Exception:
                pass
        try:
            tool_payload = {
                "tool": tool_name,
                "step": self._tool_step,
                "elapsed_ms": tool_elapsed_ms,
                "status": str(runtime_raw.get("status", "")),
                "tree_name": self._extract_tree_name(tool_input),
                "node_name": self._extract_node_name(tool_input),
                "used_structured_tool": True,
            }
            self.journal.log_runtime_event(
                event_type="tool_dispatched",
                payload=tool_payload,
            )
        except Exception:
            pass
        if tool_name == "write_script_draft":
            try:
                payload = runtime_raw.get("result", {}) if isinstance(runtime_raw, dict) else {}
                if not isinstance(payload, dict):
                    payload = {}
                skipped = bool(payload.get("skipped_placeholder_write", False))
                self.journal.log_runtime_event(
                    event_type="script_draft_write_succeeded" if str(runtime_raw.get("status", "")) == "success" else "script_draft_write_failed",
                    payload={
                        "turn_class": str((getattr(self, "_draft_tool_policy", {}) or {}).get("turn_class") or ""),
                        "block_name": str(payload.get("block_name") or tool_input.get("block_name") or "GN_Agent_Draft"),
                        "version": int(payload.get("version", 0) or 0),
                        "char_count": int(payload.get("char_count", 0) or 0),
                        "skipped_placeholder_write": skipped,
                    },
                )
                # Item 5.4: flag for end-of-turn phase transition
                if str(runtime_raw.get("status", "")) == "success" and not skipped:
                    self._draft_written_this_turn = True
            except Exception:
                pass
        # The operational shim stays in-memory for the current turn only; no per-tool
        # persistence is needed here.

    @staticmethod
    def _draft_attempt_contract_from_policy(policy: dict[str, Any]) -> DraftAttemptContract:
        if not isinstance(policy, dict):
            return DraftAttemptContract()
        return DraftAttemptContract(
            require_read_before_write=bool(policy.get("require_read_before_write", True)),
            allow_write_when_source_missing=bool(policy.get("allow_write_when_source_missing", False)),
            require_target_tree_for_write=bool(policy.get("require_target_tree_for_write", False)),
            require_structural_memory_for_write=bool(policy.get("require_structural_memory_for_write", False)),
            require_context_evidence_for_write=bool(policy.get("require_context_evidence_for_write", False)),
            require_prepared_context_for_write=bool(policy.get("require_prepared_context_for_write", False)),
            block_when_prepared_context_has_blockers=bool(policy.get("block_when_prepared_context_has_blockers", False)),
        )

    def _ensure_draft_attempt_state(self, policy: dict[str, Any]) -> DraftAttemptState:
        target_tree = str(policy.get("tree_name") or "").strip() if isinstance(policy, dict) else ""
        existing_state = getattr(self, "_draft_attempt_state", None)
        if not isinstance(existing_state, DraftAttemptState):
            has_existing_draft = bool(policy.get("existing_draft_loaded", False)) if isinstance(policy, dict) else False
            state = DraftAttemptState(
                source_read_attempted=has_existing_draft,
                source_read_succeeded=has_existing_draft,
                target_tree=target_tree,
                target_resolved=bool(target_tree),
                structural_memory_ready=bool(policy.get("fresh_structural_memory", False)) if isinstance(policy, dict) else False,
                prepared_context_read=bool(policy.get("prepared_context_pre_read", False)) if isinstance(policy, dict) else False,
            )
            setattr(self, "_draft_attempt_state", state)
            return state
        state = existing_state
        if target_tree and not state.target_tree:
            state.target_tree = target_tree
            state.target_resolved = True
        if isinstance(policy, dict) and bool(policy.get("fresh_structural_memory", False)):
            state.structural_memory_ready = True
        setattr(self, "_draft_attempt_state", state)
        return state

    def _record_draft_attempt_tool_result(
        self,
        *,
        tool_name: str,
        tool_input: dict[str, Any],
        runtime_raw: dict[str, Any],
    ) -> None:
        policy = getattr(self, "_draft_tool_policy", {}) or {}
        if not isinstance(policy, dict) or not policy.get("turn_class"):
            return
        if str(policy.get("turn_class") or "") != "draft_workspace":
            return
        state = AgentRuntime._ensure_draft_attempt_state(self, policy)
        status = str(runtime_raw.get("status", "") or "")
        result = runtime_raw.get("result", {}) if isinstance(runtime_raw.get("result"), dict) else {}
        tree_name = AgentRuntime._extract_tree_name(tool_input) or str(result.get("tree_name", "")).strip()
        if tree_name:
            state.target_tree = tree_name
            state.target_resolved = True
        if tool_name == "read_script_draft":
            state.source_read_attempted = True
            if status == "success":
                state.source_read_succeeded = True
                state.source_block_missing = False
            elif "not found" in str(runtime_raw.get("error", "") or "").lower():
                state.source_block_missing = True
        elif tool_name == "resolve_gn_workspace" and status == "success":
            selected_tree = str(result.get("selected_tree") or "").strip()
            if selected_tree:
                state.target_tree = selected_tree
                state.target_resolved = True
        elif tool_name == "prepare_draft_context" and status == "success":
            state.prepared_context_read = True
            prepared_tree = str(result.get("tree_name") or "").strip()
            if prepared_tree:
                state.target_tree = prepared_tree
                state.target_resolved = True
            if bool(result.get("context_ready", False)):
                state.structural_memory_ready = True
            write_requirements = result.get("write_requirements", {}) if isinstance(result.get("write_requirements"), dict) else {}
            blockers = write_requirements.get("blockers", []) if isinstance(write_requirements.get("blockers"), list) else []
            state.prepared_context_blockers = [
                str(item).strip()
                for item in blockers
                if str(item).strip()
            ]
            if bool(write_requirements.get("structural_memory_available", False)):
                state.structural_memory_ready = True
        elif tool_name == "build_tree_structural_memory" and status == "success":
            memory = result.get("memory", {}) if isinstance(result.get("memory"), dict) else {}
            memory_tree = str(memory.get("tree_name") or tree_name).strip()
            if memory_tree:
                state.target_tree = memory_tree
                state.target_resolved = True
            state.structural_memory_ready = True
        elif tool_name in _DRAFT_FOCAL_READ_TOOLS and status == "success":
            state.evidence_reads += 1
        elif tool_name == "write_script_draft":
            state.write_attempted = True
            if status == "success":
                state.write_succeeded = True
        try:
            self.journal.log_runtime_event(
                event_type="draft_attempt_state_updated",
                payload={
                    "tool_name": tool_name,
                    "status": status,
                    **asdict(state),
                },
            )
        except Exception:
            pass

    def _draft_write_contract_block_reason(self, policy: dict[str, Any]) -> str:
        contract = AgentRuntime._draft_attempt_contract_from_policy(policy)
        state = AgentRuntime._ensure_draft_attempt_state(self, policy)
        if contract.require_read_before_write and not state.source_read_succeeded:
            if not (state.source_block_missing and contract.allow_write_when_source_missing):
                return "draft_source_not_read"
        if contract.require_target_tree_for_write and not state.target_resolved:
            return "draft_target_not_resolved"
        if contract.require_structural_memory_for_write and not state.structural_memory_ready:
            return "draft_structural_memory_missing"
        if contract.require_prepared_context_for_write and not state.prepared_context_read:
            return "draft_context_gate_missing"
        if (
            contract.require_context_evidence_for_write
            and not state.structural_memory_ready
            and int(state.evidence_reads or 0) <= 0
        ):
            return "draft_context_not_collected"
        if contract.block_when_prepared_context_has_blockers and state.prepared_context_blockers:
            blocked = ",".join(state.prepared_context_blockers[:3])
            return f"draft_context_gate_blocked:{blocked}"
        return ""

    def _enforce_draft_tool_policy(self, tool_name: str) -> str:
        policy = getattr(self, "_draft_tool_policy", {}) or {}
        if not isinstance(policy, dict) or not policy.get("turn_class"):
            return ""
        turn_class = str(policy.get("turn_class") or "")
        if tool_name == "write_script_draft":
            if not bool(policy.get("write_allowed", False)):
                return self._block_draft_tool(tool_name, "write_not_allowed_for_turn", policy)
            contract_block = AgentRuntime._draft_write_contract_block_reason(self, policy)
            if contract_block:
                state = AgentRuntime._ensure_draft_attempt_state(self, policy)
                state.last_block_reason = contract_block
                return self._block_draft_tool(tool_name, contract_block, policy)
            return ""
        if tool_name == "read_script_draft":
            if turn_class == "draft_workspace":
                state = AgentRuntime._ensure_draft_attempt_state(self, policy)
                if bool(policy.get("existing_draft_loaded", False)) or state.source_read_succeeded:
                    return self._block_draft_tool(tool_name, "draft_source_already_read", policy)
            return ""
        if tool_name in _DRAFT_BROAD_READ_TOOLS:
            # build_tree_structural_memory: allow ONE fresh read per turn even in
            # economy_retry when the turn lacks a fresh structural memory snapshot.
            # This is the single most important read — without it the agent writes
            # against a stale tree and is guaranteed to produce broken scripts.
            if (
                tool_name == "build_tree_structural_memory"
                and not bool(policy.get("fresh_structural_memory", False))
            ):
                budget = int(policy.get("recovery_structural_budget", 0) or 0)
                used = int(policy.get("recovery_structural_used", 0) or 0)
                if used < budget:
                    policy["recovery_structural_used"] = used + 1
                    self._draft_tool_policy = policy
                    try:
                        self.journal.log_runtime_event(
                            event_type="draft_workspace_read_allowed",
                            payload={
                                "turn_class": turn_class,
                                "tool_name": tool_name,
                                "tree_name": str(policy.get("tree_name") or ""),
                                "recovery_structural_used": policy["recovery_structural_used"],
                                "recovery_structural_budget": budget,
                                "economy_retry": bool(policy.get("economy_retry", False)),
                                "reason": "fresh_structural_memory_missing",
                            },
                        )
                    except Exception:
                        pass
                    return ""
            if bool(policy.get("economy_retry", False)):
                return self._block_draft_tool(tool_name, "economy_retry_disallows_investigation", policy)
            if (
                tool_name == "get_tree_parameters"
                and turn_class == "draft_workspace"
                and str(policy.get("goal_mode") or "") == "diagnose_only"
            ):
                return ""
            if (
                tool_name == "resolve_gn_workspace"
                and not str(policy.get("tree_name") or "").strip()
            ):
                budget = int(policy.get("workspace_resolution_budget", 0) or 0)
                used = int(policy.get("workspace_resolution_used", 0) or 0)
                if used < budget:
                    policy["workspace_resolution_used"] = used + 1
                    self._draft_tool_policy = policy
                    try:
                        self.journal.log_runtime_event(
                            event_type="draft_workspace_read_allowed",
                            payload={
                                "turn_class": turn_class,
                                "tool_name": tool_name,
                                "tree_name": "",
                                "workspace_resolution_used": policy["workspace_resolution_used"],
                                "workspace_resolution_budget": budget,
                                "reason": "tree_name_missing",
                            },
                        )
                    except Exception:
                        pass
                    return ""
            return self._block_draft_tool(tool_name, "broad_or_rebuild_read_disallowed", policy)
        if tool_name in _DRAFT_FOCAL_READ_TOOLS:
            if bool(policy.get("economy_retry", False)):
                budget = int(policy.get("focal_budget", 0) or 0)
                used = int(policy.get("focal_used", 0) or 0)
                if budget <= 0:
                    return self._block_draft_tool(tool_name, "economy_retry_disallows_focal_reads", policy)
                if used >= budget:
                    policy["read_budget_exhausted"] = True
                    self._draft_tool_policy = policy
                    return self._block_draft_tool(tool_name, "economy_retry_focal_budget_exhausted", policy)
                policy["focal_used"] = used + 1
                self._draft_tool_policy = policy
                try:
                    self.journal.log_runtime_event(
                        event_type="draft_read_budget_used",
                        payload={
                            "turn_class": turn_class,
                            "tool_name": tool_name,
                            "focal_used": policy["focal_used"],
                            "focal_budget": budget,
                            "reason": "coverage_aware_economy_retry_focal_read_allowed",
                            "coverage_has_semantic_memory": bool(policy.get("coverage_has_semantic_memory", False)),
                        },
                    )
                except Exception:
                    pass
                return ""
            budget = int(policy.get("focal_budget", 0) or 0)
            used = int(policy.get("focal_used", 0) or 0)
            if bool(policy.get("fresh_structural_memory", False)) and budget <= 0:
                return self._block_draft_tool(tool_name, "fresh_structural_memory_available", policy)
            if used >= budget:
                policy["read_budget_exhausted"] = True
                self._draft_tool_policy = policy
                return self._block_draft_tool(tool_name, "focal_read_budget_exhausted", policy)
            policy["focal_used"] = used + 1
            self._draft_tool_policy = policy
            try:
                self.journal.log_runtime_event(
                    event_type="draft_read_budget_used",
                    payload={
                        "turn_class": turn_class,
                        "tool_name": tool_name,
                        "focal_used": policy["focal_used"],
                        "focal_budget": budget,
                        "reason": "minimal_focal_read_allowed",
                    },
                )
            except Exception:
                pass
        return ""

    def _block_draft_tool(self, tool_name: str, reason: str, policy: dict[str, Any]) -> str:
        try:
            self.journal.log_runtime_event(
                event_type="draft_read_budget_blocked",
                payload={
                    "turn_class": str(policy.get("turn_class") or ""),
                    "tool_name": tool_name,
                    "reason": reason,
                    "tree_name": str(policy.get("tree_name") or ""),
                    "fresh_structural_memory": bool(policy.get("fresh_structural_memory", False)),
                    "focal_used": int(policy.get("focal_used", 0) or 0),
                    "focal_budget": int(policy.get("focal_budget", 0) or 0),
                },
                status="blocked",
            )
        except Exception:
            pass
        if tool_name == "write_script_draft" and str(reason).startswith("draft_"):
            if str(reason).startswith("draft_context_gate_blocked:"):
                blockers = str(reason).split(":", 1)[1]
                return (
                    "BLOCKED: write_script_draft failed the prepared draft-context gate "
                    f"({blockers}). Resolve those context blockers before writing a full revision."
                )
            return (
                f"BLOCKED: {tool_name} does not satisfy the current draft attempt contract "
                f"({reason}). Read the canonical draft, resolve the target tree, and gather the minimum required context before writing."
            )
        return (
            f"BLOCKED: {tool_name} is outside the draft-turn read budget "
            f"({reason}). Use current draft, execution metadata, and tree_structural_memory."
        )

    def _send_screenshot_turn(self, screenshot_result: str) -> str:
        return send_screenshot_turn(self, screenshot_result)

    @staticmethod
    def _extract_tree_name(tool_input: dict[str, Any]) -> str:
        return extract_tree_name(tool_input)

    @staticmethod
    def _extract_node_name(tool_input: dict[str, Any]) -> str:
        return extract_node_name(tool_input)

    @staticmethod
    def _build_structural_index_entry(tree_payload: dict[str, Any]) -> dict[str, Any]:
        return build_structural_index_entry(tree_payload)

    def _handle_stale_local_scope_tool_failure(self, tool_name: str, result: str) -> str:
        self._local_scope = {}
        state = self._session_state if isinstance(self._session_state, dict) else {}
        state_ops.set_local_scope(state, {})
        memory = state.get("session_memory")
        if isinstance(memory, dict):
            memory["active_frame"] = ""
            memory["focus_subgraph"] = ""
            memory["relevant_nodes"] = []
            state["session_memory"] = memory
            self._session_memory = memory
        try:
            self.journal.log_runtime_event(
                event_type="local_scope_stale_cleared",
                payload={"tool": tool_name, "error": result[:240]},
                status="warning",
            )
        except Exception:
            pass
        return (
            result
            + "\nLocal focus was stale and has been cleared. "
            "Do not retry the same local-scope read this turn; fall back to the focused tree's structural memory or find_tree_nodes."
        )

    def _update_operational_state_from_tool(
        self,
        *,
        tool_name: str,
        tool_input: dict[str, Any],
        runtime_raw: dict[str, Any],
    ) -> None:
        if str(runtime_raw.get("status", "success")) != "success":
            return
        result = runtime_raw.get("result", {})
        if not isinstance(result, dict):
            result = {}
        tree_name = self._extract_tree_name(tool_input) or str(result.get("tree_name", "")).strip()
        node_name = self._extract_node_name(tool_input)
        session_memory_target_tree = str(self._session_memory.get("target_tree", "") or "").strip()
        tree_scoped_tools = {
            "get_tree_focus",
            "get_tree_parameters",
            "build_tree_structural_memory",
            "classify_tree_phases",
            "map_clinical_parameter_roles",
            "interpret_orthosis_tree_logic",
            "get_node_context",
            "get_selected_nodes_context",
            "get_active_frame_context",
            "get_local_subgraph_context",
            "get_changes_since_last_turn",
            "list_tree_nodes",
            "find_tree_nodes",
        }
        use_target_fallback = tool_name in tree_scoped_tools
        if not tree_name and session_memory_target_tree and use_target_fallback:
            self._log_session_memory_used(
                reason="target_tree_fallback_for_operational_state",
                keys=["target_tree"],
                target_tree=session_memory_target_tree,
            )
        updates: dict[str, Any] = {}
        if tree_name:
            updates["target_tree"] = tree_name
        elif use_target_fallback and session_memory_target_tree:
            updates["target_tree"] = session_memory_target_tree
        if node_name:
            updates["relevant_nodes"] = [node_name]

        if tool_name == "get_selected_nodes_context":
            selected_nodes = [
                str(node.get("name", "")).strip()
                for node in result.get("nodes", [])
                if isinstance(node, dict) and node.get("is_selected")
            ]
            self._local_scope = {
                "scope_type": "selected_nodes",
                "tree_name": tree_name,
                "node_names": [n for n in selected_nodes if n],
                "updated_at": int(time.time()),
            }
            updates["relevant_nodes"] = self._local_scope.get("node_names", [])
            self.journal.log_runtime_event(
                event_type="local_scope_used",
                payload={
                    "local_scope_used": True,
                    "scope_type": "selected_nodes",
                    "selected_nodes_count": len(self._local_scope.get("node_names", [])),
                },
            )
        elif tool_name == "get_active_frame_context":
            frame_name = str(result.get("frame_name", "")).strip()
            node_names = [
                str(node.get("name", "")).strip()
                for node in result.get("nodes", [])
                if isinstance(node, dict)
            ]
            self._local_scope = {
                "scope_type": "active_frame",
                "tree_name": tree_name,
                "frame_name": frame_name,
                "node_names": [n for n in node_names if n],
                "updated_at": int(time.time()),
            }
            updates["active_frame"] = frame_name
            updates["relevant_nodes"] = self._local_scope.get("node_names", [])
            self.journal.log_runtime_event(
                event_type="local_scope_used",
                payload={
                    "local_scope_used": True,
                    "scope_type": "active_frame",
                    "active_frame_name": frame_name,
                },
            )
        elif tool_name == "get_local_subgraph_context":
            node_names = [
                str(node.get("name", "")).strip()
                for node in result.get("nodes", [])
                if isinstance(node, dict)
            ]
            self._local_scope = {
                "scope_type": "subgraph",
                "tree_name": tree_name,
                "node_names": [n for n in node_names if n],
                "updated_at": int(time.time()),
            }
            updates["focus_subgraph"] = f"{tree_name}:{result.get('scope_mode', 'subgraph')}"
            updates["relevant_nodes"] = self._local_scope.get("node_names", [])
            self.journal.log_runtime_event(
                event_type="local_scope_used",
                payload={
                    "local_scope_used": True,
                    "scope_type": "subgraph",
                    "selected_nodes_count": len(self._local_scope.get("node_names", [])),
                },
            )
        elif tool_name == "get_changes_since_last_turn":
            self.journal.log_runtime_event(
                event_type="changes_since_last_turn",
                payload={
                    "tree_name": tree_name,
                    "changes_since_last_turn_count": int(result.get("changes_count", 0) or 0),
                },
            )

        if tool_name == "resolve_gn_workspace":
            selected_tree = str(result.get("selected_tree") or "").strip()
            if selected_tree:
                tree_name = selected_tree
                updates["target_tree"] = selected_tree
                self.journal.log_runtime_event(
                    event_type="gn_workspace_resolved",
                    payload={
                        "tree_name": selected_tree,
                        "selection_reason": result.get("selection_reason", ""),
                        "confidence": result.get("confidence", {}),
                    },
                )

        if tool_name == "build_tree_structural_memory":
            memory = result.get("memory") if isinstance(result.get("memory"), dict) else {}
            memory_tree = str(memory.get("tree_name") or tree_name).strip()
            if memory_tree:
                tree_name = memory_tree
                updates["target_tree"] = memory_tree
                state_ops.update_tree_structural_memory(self._session_state, memory_tree, memory)
                marker = memory.get("marker") if isinstance(memory.get("marker"), dict) else {}
                if marker:
                    state_ops.update_tree_change_marker(
                        self._session_state,
                        tree_name=memory_tree,
                        marker=marker,
                    )
                self.journal.log_runtime_event(
                    event_type="tree_structural_memory_updated",
                    payload={
                        "tree_name": memory_tree,
                        "node_count": memory.get("node_count", 0),
                        "phase_dominant": memory.get("phase_dominant", ""),
                        "phase_confidence": memory.get("phase_confidence", 0),
                    },
                )

        if tool_name in {
            "classify_tree_phases",
            "map_clinical_parameter_roles",
            "interpret_orthosis_tree_logic",
        }:
            semantic_tree = str(result.get("tree_name") or tree_name).strip()
            if semantic_tree:
                tree_name = semantic_tree
                updates["target_tree"] = semantic_tree
                state_ops.update_tree_semantic_memory(self._session_state, semantic_tree, tool_name, result)
                self.journal.log_runtime_event(
                    event_type="tree_semantic_memory_updated",
                    payload={
                        "tree_name": semantic_tree,
                        "semantic_key": tool_name,
                    },
                )

        if tool_name == "get_changes_since_last_turn":
            current_marker = result.get("current_marker", {}) if isinstance(result.get("current_marker"), dict) else {}
            if tree_name and current_marker and bool(tool_input.get("update_marker", True)):
                state_ops.update_tree_change_marker(
                    self._session_state,
                    tree_name=tree_name,
                    marker=current_marker,
                )
            if int(result.get("changes_count", 0) or 0) > 0:
                state_ops.mark_tree_structural_memory_stale(
                    self._session_state,
                    tree_name,
                    reason="changes_since_last_turn_detected_changes",
                )


        state_ops.set_local_scope(self._session_state, self._local_scope)
        previous_memory = deepcopy(self._session_memory)
        self._session_memory = state_ops.update_session_memory(self._session_state, updates)
        if self._session_memory != previous_memory:
            changed_keys = sorted(
                key
                for key in set(previous_memory) | set(self._session_memory)
                if previous_memory.get(key) != self._session_memory.get(key)
            )
            self.journal.log_runtime_event(
                event_type="session_memory_updated",
                payload={
                    "session_memory_updated": True,
                    "target_tree": self._session_memory.get("target_tree", ""),
                    "relevant_nodes_count": len(self._session_memory.get("relevant_nodes", [])),
                    "changed_keys": changed_keys,
                },
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _normalize_tool_input(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(tool_input or {})
        if tool_name == "write_script_draft":
            policy = getattr(self, "_draft_tool_policy", {}) or {}
            edit_mode = str(policy.get("edit_mode") or "preserve_and_refine").strip()
            goal_mode = str(policy.get("goal_mode") or "").strip()
            if goal_mode:
                normalized.setdefault("goal_mode", goal_mode)
            goal_guidance = policy.get("goal_guidance")
            if isinstance(goal_guidance, dict) and goal_guidance:
                normalized.setdefault("goal_guidance", deepcopy(goal_guidance))
            expected_parameter_refs = policy.get("expected_parameter_refs", [])
            if isinstance(expected_parameter_refs, list) and expected_parameter_refs:
                normalized.setdefault(
                    "expected_parameter_refs",
                    [str(item) for item in expected_parameter_refs if str(item).strip()],
                )
            expected_focus_regions = policy.get("expected_focus_regions", [])
            if isinstance(expected_focus_regions, list) and expected_focus_regions:
                normalized.setdefault(
                    "expected_focus_regions",
                    [str(item) for item in expected_focus_regions if str(item).strip()],
                )
            if edit_mode == "intentional_rebuild":
                normalized.setdefault("allow_capability_regression", True)
            if edit_mode == "intentional_retarget":
                normalized.setdefault("allow_tree_change", True)
                normalized.setdefault("allow_capability_regression", True)
            try:
                active_session = getattr(self, "_active_v1_session", None)
                identity = getattr(active_session, "identity", None)
                session_id = str(getattr(identity, "session_id", "") or "").strip()
                if session_id:
                    normalized.setdefault("session_id", session_id)
            except Exception:
                pass
            try:
                normalized.setdefault("project_root", str(self.project_root))
            except Exception:
                pass
        return normalized

    def _load_knowledge_snippet(self, rel_path: Path, *, max_chars: int) -> str:
        return load_knowledge_snippet(self.project_root, rel_path, max_chars=max_chars)

    def _recent_messages(self, last_n: int = 12) -> list[dict[str, Any]]:
        if len(self._messages) <= last_n:
            return list(self._messages)
        return list(self._messages[-last_n:])

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, len(text) // 4)

    def _build_target_summary(self) -> dict[str, str]:
        canonical = self._canonical_gn_target if isinstance(self._canonical_gn_target, dict) else {}
        if canonical:
            return {
                "object": str(canonical.get("object") or "").strip() or "(not set)",
                "modifier": str(canonical.get("modifier") or "").strip() or "(not set)",
                "node_group": str(canonical.get("tree_name") or "").strip() or "(not set)",
            }
        focus = getattr(self._active_v1_session, "focus", None)
        return {
            "object": str(getattr(focus, "object_name", "") or "").strip() or "(not set)",
            "modifier": str(getattr(focus, "modifier_name", "") or "").strip() or "(not set)",
            "node_group": str(getattr(focus, "tree_name", "") or "").strip() or "(not set)",
        }

    def _log_session_memory_used(self, *, reason: str, keys: list[str], **extra: Any) -> None:
        normalized_reason = str(reason or "").strip()
        if not normalized_reason or normalized_reason in self._session_memory_usage_reasons:
            return
        self._session_memory_usage_reasons.add(normalized_reason)
        payload = {
            "used": True,
            "reason": normalized_reason,
            "keys": list(keys),
        }
        payload.update(extra)
        self.journal.log_runtime_event(
            event_type="session_memory_used",
            payload=payload,
        )

    @staticmethod
    def _format_runtime_tool_result(response: dict[str, Any]) -> str:
        status = response.get("status", "success")
        if status == "blocked":
            result_payload = response.get("result", {})
            if not isinstance(result_payload, dict):
                result_payload = {}
            return json.dumps(
                {
                    "status": "blocked",
                    "error": response.get("error", "Blocked by safety policy"),
                    "tool_name": response.get("tool_name"),
                    "safety": response.get("safety", {}),
                    "result": result_payload,
                },
                ensure_ascii=False,
            )
        if status == "error":
            return f"ERROR: {response.get('error', 'Unknown error')}"

        result = response.get("result")
        if isinstance(result, dict) and "image_base64" in result:
            return f"SCREENSHOT_BASE64:{result.get('image_base64', '')}"
        if result is not None:
            return json.dumps(result, ensure_ascii=False, indent=2)
        raw = response.get("raw") if isinstance(response.get("raw"), dict) else {}
        stdout = raw.get("stdout")
        if isinstance(stdout, str) and stdout.strip():
            return stdout.strip()
        return json.dumps(response, ensure_ascii=False)

    @staticmethod
    def _extract_text(response) -> str:
        return extract_text(response)

    def _request_with_retry(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
    ):
        return request_with_retry(
            self,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            max_retries=_MAX_RETRIES,
            retry_wait_seconds=_RETRY_WAIT_SECONDS,
            is_transient_api_error_fn=self._is_transient_api_error,
        )

    def _stream_with_retry(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
    ):
        return stream_with_retry(
            self,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            max_retries=_MAX_RETRIES,
            retry_wait_seconds=_RETRY_WAIT_SECONDS,
            is_transient_api_error_fn=self._is_transient_api_error,
            on_text_chunk=self.on_text_chunk,
        )

    @staticmethod
    def _is_transient_api_error(exc: Exception) -> bool:
        return is_transient_api_error(exc)
