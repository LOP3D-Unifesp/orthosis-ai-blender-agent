"""Agent loop helpers for model rounds and tool-use dispatch."""

from __future__ import annotations

import json
import time
from typing import Any

# Budget limits to prevent runaway context growth and rate-limit hits.
_MAX_ROUNDS = 10          # hard-ceiling on API round-trips per turn (safety net)
_MAIN_MAX_ROUNDS = 8      # default budget for main reasoning phase (W4-T2)
_DISCOVERY_MAX_READS = 2  # max direct tool calls in discovery phase (W4-T1)
_MAX_TOOL_RESULT_CHARS = 6000   # truncate individual tool results beyond this
# Heavier truncation for known high-volume read tools (tree structure etc.)
_HEAVY_READ_TOOLS = {
    "get_local_subgraph_context",
    "classify_tree_phases",
    "map_clinical_parameter_roles",
    "interpret_orthosis_tree_logic",
    "get_scene_summary",
    "get_gn_hosts",
    "analyze_gn_state",
    "analyze_scene",
}
_MAX_READ_RESULT_CHARS = 4000

# Item 5.1: Portuguese labels shown in the panel during tool execution.
# Key = tool name, value = base label (round info appended at runtime).
_TOOL_STATUS_PT: dict[str, str] = {
    "get_node_context": "Lendo contexto do nó",
    "get_selected_nodes_context": "Lendo nós selecionados",
    "get_active_frame_context": "Lendo frame ativo",
    "get_local_subgraph_context": "Lendo subgrafo",
    "get_scene_summary": "Lendo cena",
    "get_gn_hosts": "Listando objetos GN",
    "get_tree_parameters": "Lendo parâmetros da árvore",
    "get_changes_since_last_turn": "Verificando mudanças",
    "find_tree_nodes": "Buscando nós",
    "list_tree_nodes": "Listando nós",
    "resolve_gn_workspace": "Resolvendo workspace GN",
    "build_tree_structural_memory": "Lendo árvore GN",
    "read_script_draft": "Lendo draft",
    "write_script_draft": "Escrevendo draft",
    "prepare_draft_context": "Preparando contexto de draft",
    "classify_tree_phases": "Classificando fases da árvore",
    "map_clinical_parameter_roles": "Mapeando parâmetros clínicos",
    "interpret_orthosis_tree_logic": "Interpretando lógica da órtese",
    "analyze_gn_state": "Analisando estado GN",
    "analyze_scene": "Analisando cena",
    "capture_screenshot": "Capturando viewport",
    "query_node_types": "Consultando tipos de nó",
    "apply_simulator_payload": "Aplicando parâmetros de simulador",
}


def _truncate_result(text: str, tool_name: str = "") -> str:
    """Truncate a tool result string, preserving a note about truncation."""
    max_chars = _MAX_READ_RESULT_CHARS if tool_name in _HEAVY_READ_TOOLS else _MAX_TOOL_RESULT_CHARS
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n... [truncated, {len(text) - max_chars} chars omitted]"


# ---------------------------------------------------------------------------
# Assistant-content compression
#
# In multi-round loops the full assistant message (including tool_use blocks
# with their complete ``input`` payloads) is re-sent to the API on every
# subsequent round.  For ``execute_code`` this means re-transmitting the
# entire Python script on each round — potentially thousands of tokens per
# call.
#
# Once a tool_use block has been executed and its result returned in the
# following user message, the full ``input`` payload is no longer needed.
# We replace it with a compact stub that preserves the block identity
# (``id`` + ``name``) while cutting re-sent tokens dramatically.
# ---------------------------------------------------------------------------

def _build_input_stub(tool_name: str, inp: dict) -> dict:
    """Return a compact stub for an already-executed tool input.

    Preserves enough context for the model to understand what was called
    without re-sending the full payload.
    """
    inp = inp or {}
    if tool_name == "execute_code":
        code = inp.get("code", "") or inp.get("script", "")
        return {"code": f"[{len(code)}-char script]"}
    if tool_name == "make_plan":
        goal = str(inp.get("goal", ""))[:80]
        return {"goal": goal}
    if tool_name in {"read_script_draft", "write_script_draft", "prepare_draft_context"}:
        # Draft tools are stateful; preserve their small intent-shaping args so
        # later rounds can see what was already read/written instead of asking
        # for the same draft again.
        keep: dict[str, Any] = {}
        for key in (
            "block_name",
            "tree_name",
            "goal_mode",
            "has_existing_draft",
            "prefer_from_scratch",
            "description",
            "revision_changed_from_previous",
        ):
            if key in inp:
                value = inp.get(key)
                keep[key] = str(value)[:180] if isinstance(value, str) else value
        if tool_name == "write_script_draft" and "code" in inp:
            keep["code"] = f"[{len(str(inp.get('code') or ''))}-char draft script]"
        return keep or {"tool_input": "preserved_empty"}
    # Generic: keep up to 3 keys, truncate long values
    return {k: (str(v)[:60] if len(str(v)) > 60 else v) for k, v in list(inp.items())[:3]}


def _compress_tool_inputs_in_history(messages: list) -> None:
    """In-place: compress tool_use inputs in resolved assistant messages.

    Iterates all assistant messages followed by a user message containing
    tool_results (i.e. the round is complete).  Replaces large ``input``
    payloads with compact stubs — the API only needs ``id``, ``name``, and
    ``type`` to validate the turn structure; the ``input`` content is not
    re-validated.

    Inputs already small (≤200 chars) are left untouched.
    Safe to call every round — already-compressed blocks are skipped.
    """
    for i in range(len(messages) - 1):
        msg = messages[i]
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue

        content = msg.get("content", [])
        if not isinstance(content, list):
            continue

        # Only compress rounds that are already resolved (next msg has tool_results)
        nxt = messages[i + 1]
        if not isinstance(nxt, dict) or nxt.get("role") != "user":
            continue
        nxt_content = nxt.get("content", [])
        if not isinstance(nxt_content, list):
            continue
        has_results = any(
            (b.get("type") if isinstance(b, dict) else getattr(b, "type", "")) == "tool_result"
            for b in nxt_content
        )
        if not has_results:
            continue

        # Compress tool_use blocks whose input is large
        new_content = []
        changed = False
        for block in content:
            btype = block.get("type") if isinstance(block, dict) else getattr(block, "type", "")
            if btype != "tool_use":
                new_content.append(block)
                continue

            bid = block.get("id") if isinstance(block, dict) else getattr(block, "id", "")
            bname = block.get("name") if isinstance(block, dict) else getattr(block, "name", "")
            binput = block.get("input", {}) if isinstance(block, dict) else getattr(block, "input", {})

            if len(str(binput or {})) <= 200:
                new_content.append(block)
                continue  # Already small — no benefit compressing

            new_content.append({
                "type": "tool_use",
                "id": bid,
                "name": bname,
                "input": _build_input_stub(bname, binput),
            })
            changed = True

        if changed:
            messages[i] = {"role": "assistant", "content": new_content}


def agent_loop(
    runtime: Any,
    system: str,
    messages: list[dict[str, Any]],
    max_tokens: int = 4096,
    excluded_tools: "frozenset[str] | None" = None,
    max_rounds: int | None = None,
) -> str:
    """Run the tool-use agent loop.

    *max_rounds* caps how many API round-trips this call may make.
    Defaults to ``_MAIN_MAX_ROUNDS`` (8) when omitted by GN-relevant callers
    that pass an explicit value, or ``_MAX_ROUNDS`` (10) as absolute safety net.
    Callers that want the legacy "no limit" behaviour pass ``max_rounds=None``
    and the old ``_MAX_ROUNDS`` ceiling applies as before.
    """
    effective_max_rounds = min(
        _MAX_ROUNDS,  # hard ceiling — never exceed
        max_rounds if max_rounds is not None else _MAX_ROUNDS,
    )
    runtime._last_agent_loop_truncated = False
    runtime._last_agent_loop_round_limit_hit = False
    last_text = ""
    _consecutive_truncations = 0  # halts loop if model keeps hitting max_tokens
    _total_truncations = 0  # total max_tokens hits this turn (not reset by successful rounds)
    _use_streaming = callable(getattr(runtime, "on_text_chunk", None))

    # Temporarily filter tools for this turn.
    _original_tools = runtime.tools
    if excluded_tools:
        runtime.tools = [t for t in _original_tools if t.get("name") not in excluded_tools]

    try:
        for _round in range(effective_max_rounds):
            request_t0 = time.time()
            if _use_streaming:
                response = runtime._stream_with_retry(
                    system=system, messages=messages, max_tokens=max_tokens
                )
            else:
                response = runtime._request_with_retry(
                    system=system, messages=messages, max_tokens=max_tokens
                )
            elapsed_ms = int((time.time() - request_t0) * 1000)

            usage = getattr(response, "usage", None)
            if usage:
                input_tokens = getattr(usage, "input_tokens", 0)
                output_tokens = getattr(usage, "output_tokens", 0)
                runtime.journal.accumulate_tokens(input_tokens, output_tokens)

                # Prompt-cache fields — present only when cache_control blocks were sent.
                # cache_creation_input_tokens: tokens written to cache (charged at 1.25x).
                # cache_read_input_tokens:     tokens served from cache  (charged at 0.10x).
                cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
                cache_read  = getattr(usage, "cache_read_input_tokens",     0) or 0

                payload: dict = {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "round_time_ms": elapsed_ms,
                    "round": _round + 1,
                    "max_rounds": effective_max_rounds,
                    "model": getattr(runtime, "model", ""),
                    "max_tokens": max_tokens,
                }
                if cache_write:
                    payload["cache_write_tokens"] = cache_write
                if cache_read:
                    payload["cache_read_tokens"] = cache_read

                runtime.journal.log_runtime_event(
                    event_type="api_usage",
                    payload=payload,
                )

            assistant_content = response.content
            messages.append({"role": "assistant", "content": assistant_content})
            last_text = runtime._extract_text(response)
            runtime._messages.append({"role": "assistant", "content": last_text})

            if response.stop_reason == "end_turn":
                return last_text

            _response_truncated = response.stop_reason == "max_tokens"
            if _response_truncated:
                runtime._last_agent_loop_truncated = True
                _consecutive_truncations += 1
                _total_truncations += 1
                try:
                    runtime.journal.log_runtime_event(
                        event_type="response_truncated",
                        payload={
                            "round": _round + 1,
                            "model": getattr(runtime, "model", ""),
                            "max_tokens": max_tokens,
                            "stop_reason": "max_tokens",
                            "consecutive": _consecutive_truncations,
                            "total": _total_truncations,
                        },
                        status="warning",
                    )
                except Exception:
                    pass
                # Abort on 2 truncations total in this turn (not just consecutive).
                # Alternating trunc / ok rounds used to keep the counter at 1 forever,
                # letting the loop burn through _MAX_ROUNDS. Counting total hits catches
                # that pattern and stops the bleed.
                if _total_truncations >= 2:
                    return (
                        f"Resposta truncada {_total_truncations}x neste turno "
                        f"(max_tokens={max_tokens} insuficiente para esta tarefa). "
                        "Parando para preservar créditos. "
                        "Divida a tarefa em partes menores (ex: criar sockets em lotes)."
                    )
            else:
                _consecutive_truncations = 0

            tool_results = []
            for block in assistant_content:
                if getattr(block, "type", "") != "tool_use":
                    continue

                # When the response was cut off at max_tokens, execute_code blocks
                # contain a truncated/incomplete Python script. Running it would
                # produce syntax errors or corrupt GN state. Return an error so the
                # model can recover gracefully instead of retrying the broken script
                # in an infinite loop.
                if _response_truncated and getattr(block, "name", "") in {"execute_code", "write_script_draft"}:
                    tool_name = getattr(block, "name", "")
                    try:
                        runtime.journal.log_runtime_event(
                            event_type="truncated_tool_candidate",
                            payload={
                                "tool_name": tool_name,
                                "code": str((block.input or {}).get("code", "")),
                                "round": _round + 1,
                                "max_tokens": max_tokens,
                            },
                            status="warning",
                        )
                    except Exception:
                        pass
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": (
                            (
                                "ERRO: execute_code cancelado — resposta foi truncada antes de "
                                "completar o script (max_tokens atingido). O código estava incompleto "
                                "e não foi executado. Gere um script mais curto ou divida em etapas."
                            )
                            if tool_name == "execute_code"
                            else (
                                "ERRO: write_script_draft cancelado — a resposta foi truncada antes "
                                "de completar a revisão. O draft candidato estava incompleto e não foi "
                                "salvo. Gere uma revisão menor ou divida o trabalho em etapas."
                            )
                        ),
                    })
                    continue

                # Item 5.1: update Portuguese status before the socket call so the
                # panel callback can read it and display something meaningful.
                try:
                    _pt_label = _TOOL_STATUS_PT.get(block.name, block.name)
                    runtime._current_tool_status = (
                        f"{_pt_label} (round {_round + 1}/{effective_max_rounds})..."
                    )
                except Exception:
                    pass

                runtime._tool_step += 1
                if runtime.on_tool_call:
                    try:
                        runtime.on_tool_call(block.name, runtime._tool_step)
                    except Exception:
                        pass
                result = runtime._execute_tool(block.name, block.input, elapsed_ms)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": _truncate_result(result, block.name),
                    }
                )
                if block.name == "write_script_draft":
                    try:
                        parsed_result = json.loads(result)
                    except Exception:
                        parsed_result = {}
                    write_blocked = isinstance(parsed_result, dict) and str(parsed_result.get("status") or "") == "blocked"
                    write_succeeded = (
                        isinstance(parsed_result, dict)
                        and (
                            str(parsed_result.get("status") or "") == "success"
                            or bool(parsed_result.get("block_name") and parsed_result.get("version"))
                            or bool(parsed_result.get("block_name") and parsed_result.get("char_count"))
                        )
                    )
                    if write_succeeded:
                        runtime._halt_execution = True
                        runtime._halt_message = "Draft salvo com sucesso; encerrando o turno para reportar a revisão."
                        try:
                            runtime.journal.log_runtime_event(
                                event_type="agent_loop_halted_after_draft_write",
                                payload={
                                    "tool_name": block.name,
                                    "version": parsed_result.get("version", 0) if isinstance(parsed_result, dict) else 0,
                                    "char_count": parsed_result.get("char_count", 0) if isinstance(parsed_result, dict) else 0,
                                },
                            )
                        except Exception:
                            pass
                    elif write_blocked:
                        result_payload = parsed_result.get("result", {}) if isinstance(parsed_result.get("result"), dict) else {}
                        reject_reason = str(result_payload.get("reject_reason") or "")
                        semantic_block = reject_reason.startswith((
                            "regression_lost_live_node_refs",
                            "regression_replaced_live_node_refs",
                            "regression_lost_expected_parameters",
                            "regression_replaced_expected_parameters",
                            "regression_lost_focus_regions",
                            "regression_replaced_focus_regions",
                            "target_tree_changed:",
                            "regression_candidate_too_small_vs_existing:",
                        ))
                        blocked_write_count = sum(
                            1
                            for item in getattr(runtime, "_current_turn_tools", [])
                            if isinstance(item, dict)
                            and str(item.get("name") or "") == "write_script_draft"
                            and str(item.get("status") or "") == "blocked"
                        )
                        if semantic_block and blocked_write_count <= 1:
                            try:
                                runtime.journal.log_runtime_event(
                                    event_type="agent_loop_continued_after_draft_write_blocked",
                                    payload={
                                        "tool_name": block.name,
                                        "reject_reason": reject_reason[:200],
                                        "blocked_write_count": blocked_write_count,
                                    },
                                    status="warning",
                                )
                            except Exception:
                                pass
                            continue
                        runtime._halt_execution = True
                        runtime._halt_message = "Draft bloqueado pela validacao; encerrando o turno para reportar o motivo."
                        try:
                            runtime.journal.log_runtime_event(
                                event_type="agent_loop_halted_after_draft_write_blocked",
                                payload={
                                    "tool_name": block.name,
                                    "error": str(parsed_result.get("error") or "")[:300],
                                },
                                status="blocked",
                            )
                        except Exception:
                            pass
                if runtime._halt_execution:
                    messages.append({"role": "user", "content": tool_results})
                    return runtime._halt_message or result

            if not tool_results:
                return last_text

            messages.append({"role": "user", "content": tool_results})
            # Compress resolved tool_use inputs to cut re-sent tokens on next round.
            _compress_tool_inputs_in_history(messages)

        # Exceeded round limit — log and return whatever text we have.
        runtime._last_agent_loop_round_limit_hit = True
        try:
            runtime.journal.log_runtime_event(
                event_type="agent_loop_round_limit",
                payload={"rounds": effective_max_rounds, "max_rounds": effective_max_rounds},
                status="warning",
            )
        except Exception:
            pass
        return last_text or (
            f"Atingi o limite de {effective_max_rounds} chamadas de API neste turno. "
            "Parando para preservar seus créditos. "
            "Se algo ficou incompleto, descreva o que falta e continuamos."
        )
    finally:
        runtime.tools = _original_tools


def send_screenshot_turn(runtime: Any, screenshot_result: str) -> str:
    marker = "SCREENSHOT_BASE64:"
    if marker not in screenshot_result:
        return "Screenshot capture failed: no image payload returned."
    b64_data = screenshot_result.split(marker, 1)[1].strip()

    response = runtime.client.messages.create(
        model=runtime.model,
        max_tokens=512,
        system=(
            "You are analyzing a Blender viewport screenshot. "
            "Respond in 2-3 sentences maximum. Focus only on what is visually wrong or notable."
        ),
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": b64_data,
                        },
                    },
                    {"type": "text", "text": "What do you observe in this viewport?"},
                ],
            }
        ],
    )
    return runtime._extract_text(response)
