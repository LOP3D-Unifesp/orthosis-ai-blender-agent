"""Run real Blender validation for the unified draft workspace.

This script is intended to be executed with:
blender --background --python tools/blender_runtime_validation.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import bpy


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _status(name: str, ok: bool, **extra):
    payload = {"ok": bool(ok)}
    payload.update(extra)
    return name, payload


def _ensure_tree() -> str:
    tree_name = "Biomodelo_GN"
    tree = bpy.data.node_groups.get(tree_name)
    if tree is None:
        tree = bpy.data.node_groups.new(tree_name, "GeometryNodeTree")
    if not tree.nodes.get("ORTHOSIS_CONTEXT"):
        frame = tree.nodes.new("NodeFrame")
        frame.name = "ORTHOSIS_CONTEXT"
        frame.label = "Palm/metacarpal orthosis context"
    if not tree.nodes.get("ORTHOSIS_AGENT_VALIDATION"):
        frame = tree.nodes.new("NodeFrame")
        frame.name = "ORTHOSIS_AGENT_VALIDATION"
        frame.label = "Validation draft target"
    return tree_name


def _valid_script(tree_name: str, label: str) -> str:
    return "\n".join([
        "import bpy",
        f"tree = bpy.data.node_groups.get({tree_name!r})",
        "if tree is None:",
        f"    raise RuntimeError({tree_name!r} + ' not found')",
        "nodes = tree.nodes",
        "links = tree.links",
        "frame = nodes.get('ORTHOSIS_AGENT_VALIDATION') or nodes.new('NodeFrame')",
        "frame.name = 'ORTHOSIS_AGENT_VALIDATION'",
        f"frame.label = {label!r}",
        "frame.location = (0, 0)",
        "print('validation draft prepared for manual Blender execution')",
        "# Complete enough to be a real full draft revision.",
        "# " + ("orthosis palm metacarpal biomodel GN revision " * 12),
    ])


def main() -> None:
    from blender_addon.handler import TurnContext
    from blender_addon.handler.workspace import handle as handle_workspace
    from blender_addon.handler.feedback_classifier import _classify_execution_feedback
    from blender_addon.operation_journal import OperationJournal
    from blender_addon.runtime.router import ClassifierMeta, TurnClass
    from blender_addon.runtime import Runtime
    from blender_addon.core.runtime import AgentRuntime
    from blender_addon.session.schema import DraftedScript
    from blender_addon.tools.handlers import handle_read_script_draft, handle_write_script_draft

    validation_dir = PROJECT_ROOT / "runtime" / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    report_path = validation_dir / f"blender_runtime_validation_{int(time.time())}.json"

    tree_name = _ensure_tree()
    results: dict[str, dict] = {}

    partial = handle_write_script_draft({
        "block_name": "GN_Agent_Draft",
        "code": "print()",
        "description": "Tiny accidental draft",
        "tree_name": tree_name,
    })
    results["partial_write_blocked"] = {
        "status": partial.get("status"),
        "error": partial.get("error", ""),
    }

    valid = handle_write_script_draft({
        "block_name": "GN_Agent_Draft",
        "code": _valid_script(tree_name, "Orthosis palm/metacarpal validation"),
        "description": "Real Blender validation draft for orthosis GN tree",
        "tree_name": tree_name,
    })
    read = handle_read_script_draft({"block_name": "GN_Agent_Draft"})
    text_block = bpy.data.texts.get("GN_Agent_Draft")
    results["real_text_block_write"] = {
        "write_status": valid.get("status"),
        "write_error": valid.get("error", ""),
        "read_status": read.get("status"),
        "read_error": read.get("error", ""),
        "exists": text_block is not None,
        "char_count": len(text_block.as_string()) if text_block is not None else 0,
        "revision_validity": ((read.get("result") or {}).get("current_revision_validity") if read.get("status") == "success" else ""),
        "revision_block_name": (valid.get("result") or {}).get("revision_block_name", ""),
    }

    class _ValidationRuntime:
        def __init__(self):
            self._messages = []
            self._session_memory = {
                "last_goal": "Construir e corrigir uma arvore GN para ortese baseada em biomodelo da palma/metacarpos.",
                "last_hypothesis": "O draft precisa ser completo antes de ir para o Text Editor.",
                "target_tree": tree_name,
                "relevant_nodes": ["ORTHOSIS_CONTEXT"],
            }
            self._session_state = {"tree_structural_memory": {}}
            self._draft_tool_policy = {}
            self._current_turn_tools = []
            self.journal = type("Journal", (), {"log_runtime_event": lambda self, **kwargs: None})()

        def _agent_loop(self, *_args, **_kwargs):
            self._execute_tool("write_script_draft", {
                "block_name": "GN_Agent_Draft_Blocked_Handler",
                "code": "print()",
                "description": "Tiny accidental draft from handler",
                "tree_name": tree_name,
            }, 0)
            return "Ok, draft criado."

        def _execute_tool(self, name, tool_input, _elapsed):
            if name == "write_script_draft":
                raw = handle_write_script_draft(tool_input)
            elif name == "read_script_draft":
                raw = handle_read_script_draft(tool_input)
            else:
                raw = {"status": "success", "result": {"memory": {"node_count": 1, "tree_name": tree_name}}}
            payload = raw.get("result", {}) if isinstance(raw, dict) else {}
            self._current_turn_tools.append({
                "name": name,
                "input": tool_input,
                "result": json.dumps(raw, ensure_ascii=False)[:300],
                "status": str(raw.get("status", "")),
                "result_payload": payload if isinstance(payload, dict) else {},
            })
            return json.dumps(raw, ensure_ascii=False)

    runtime = Runtime(project_root=PROJECT_ROOT)
    session = runtime.v1_session_for("")
    try:
        session.update_focus(
            blend_path="",
            object_name="Validation Biomodel",
            modifier_name="GeometryNodes",
            tree_name=tree_name,
        )
    except Exception:
        pass
    session.execution_state.set_phase("drafting")
    session.execution_state.current_draft = DraftedScript(
        block_name="GN_Agent_Draft",
        description="Real Blender validation draft for orthosis GN tree",
        tree_name=tree_name,
        version=int((read.get("result") or {}).get("version", 1) or 1),
        revision_validity=str((read.get("result") or {}).get("current_revision_validity", "valid")),
    )
    session.operational_state.session_memory = {
        "last_goal": "Construir e corrigir uma arvore GN para ortese baseada em biomodelo da palma/metacarpos.",
        "last_hypothesis": "A arvore precisa preservar contexto anatomico enquanto organiza controles procedurais da ortese.",
        "target_tree": tree_name,
        "relevant_nodes": ["ORTHOSIS_CONTEXT", "ORTHOSIS_AGENT_VALIDATION"],
    }
    runtime.save_v1_session(session)

    class _InquiryRuntime(_ValidationRuntime):
        def __init__(self, product_runtime):
            super().__init__()
            self._product_runtime = product_runtime
            self._session_state = {"tree_structural_memory": {}}
            self.tool_calls: list[str] = []
            self.last_system = ""

        def _execute_tool(self, name, tool_input, _elapsed):
            self.tool_calls.append(name)
            if name == "build_tree_structural_memory":
                raw = self._product_runtime.execute_tool_call(
                    tool_name=name,
                    tool_input=tool_input,
                    route="product",
                    output_mode="compact",
                    blend_path="",
                )
            else:
                raw = {"status": "error", "error": f"Unexpected inquiry validation tool: {name}"}
            result = raw.get("result", {}) if isinstance(raw, dict) else {}
            memory = result.get("memory", result) if isinstance(result, dict) else {}
            memory_tree = str(memory.get("tree_name") or tool_input.get("tree_name") or "").strip()
            if name == "build_tree_structural_memory" and memory_tree and isinstance(memory, dict):
                self._session_state.setdefault("tree_structural_memory", {})[memory_tree] = dict(memory)
            payload = result if isinstance(result, dict) else {}
            self._current_turn_tools.append({
                "name": name,
                "input": dict(tool_input),
                "result": json.dumps(raw, ensure_ascii=False)[:300],
                "status": str(raw.get("status", "")),
                "result_payload": payload,
            })
            return json.dumps(raw, ensure_ascii=False)

        def _agent_loop(self, system, *_args, **_kwargs):
            self.last_system = str(system or "")
            return "Inquiry validation answer."

    inquiry_runtime = _InquiryRuntime(runtime)
    inquiry_session = runtime.v1_session_for("")
    try:
        inquiry_session.update_focus(
            blend_path="",
            object_name="Validation Biomodel",
            modifier_name="GeometryNodes",
            tree_name=tree_name,
        )
    except Exception:
        pass
    inquiry_session.operational_state.tree_structural_memory = {}
    inquiry_ctx = TurnContext(
        session=inquiry_session,
        message="qual a estrutura da arvore?",
        meta=ClassifierMeta(
            turn_class=TurnClass.CONTEXT_INQUIRY,
            goal_mode="inquiry",
            needs_baseline_refresh=True,
        ),
        blend_path="",
        _runtime=inquiry_runtime,
        knowledge_dir=PROJECT_ROOT / "knowledge" / "domain",
    )
    inquiry_result = handle_workspace(inquiry_ctx, "inquiry")
    inquiry_memory = (
        inquiry_runtime._session_state
        .get("tree_structural_memory", {})
        .get(tree_name, {})
    )
    results["inquiry_structural_discovery_smoke"] = {
        "response": str(inquiry_result.response_text or ""),
        "build_tree_structural_memory_calls": inquiry_runtime.tool_calls.count("build_tree_structural_memory"),
        "tool_calls": list(inquiry_runtime.tool_calls),
        "node_count": int(inquiry_memory.get("node_count", 0) or 0) if isinstance(inquiry_memory, dict) else 0,
        "contains_context_frame": "ORTHOSIS_CONTEXT" in inquiry_runtime.last_system,
        "contains_validation_frame": "ORTHOSIS_AGENT_VALIDATION" in inquiry_runtime.last_system,
        "baseline_has_summary": bool(getattr(getattr(inquiry_session, "baseline_workspace", None), "structural_summary", None)),
    }

    blocked_session = runtime.v1_session_for("")
    blocked_session.execution_state.set_phase("drafting")
    blocked_session.execution_state.current_draft = DraftedScript(
        block_name="GN_Agent_Draft_Blocked_Handler",
        description="Blocked handler validation draft",
        tree_name=tree_name,
        version=1,
    )
    handle_write_script_draft({
        "block_name": "GN_Agent_Draft_Blocked_Handler",
        "code": _valid_script(tree_name, "Blocked handler source draft"),
        "description": "Blocked handler source draft",
        "tree_name": tree_name,
    })
    blocked_ctx = TurnContext(
        session=blocked_session,
        message="corrige esse draft",
        meta=ClassifierMeta(turn_class=TurnClass.DRAFT_WORKSPACE),
        blend_path="",
        _runtime=_ValidationRuntime(),
        knowledge_dir=PROJECT_ROOT / "knowledge" / "domain",
    )
    blocked_result = handle_workspace(blocked_ctx, "focal_correction")
    results["handler_blocked_write_not_success"] = {
        "response_preview": str(blocked_result.response_text or "")[:300],
        "text_block_exists": bpy.data.texts.get("GN_Agent_Draft_Blocked_Handler") is not None,
        "reported_blocked": "bloqueada" in str(blocked_result.response_text or "").lower(),
    }

    class _MissingDraftRuntime(_ValidationRuntime):
        def _agent_loop(self, *_args, **_kwargs):
            raise RuntimeError("agent_loop should not run when draft source block is missing")

    missing_session = runtime.v1_session_for("")
    missing_session.execution_state.set_phase("drafting")
    missing_session.execution_state.current_draft = DraftedScript(
        block_name="GN_Agent_Draft",
        description="Missing source draft validation",
        tree_name=tree_name,
        version=1,
    )
    missing_session.execution_state.pending_draft_action = "write_confirmed_draft_revision"
    missing_session.execution_state.retry_requires_draft_change = True
    missing_ctx = TurnContext(
        session=missing_session,
        message="Vamos tentar escrever esse draft denovo?",
        meta=ClassifierMeta(turn_class=TurnClass.DRAFT_WORKSPACE),
        blend_path="",
        _runtime=_MissingDraftRuntime(),
        knowledge_dir=PROJECT_ROOT / "knowledge" / "domain",
    )
    if bpy.data.texts.get("GN_Agent_Draft") is not None:
        bpy.data.texts.remove(bpy.data.texts["GN_Agent_Draft"])
    try:
        missing_result = handle_workspace(missing_ctx, "focal_correction")
        missing_text = str(missing_result.response_text or "")
        missing_handler_escaped = False
    except Exception as exc:
        missing_text = str(exc)
        missing_handler_escaped = True
    results["missing_draft_source_stops_early"] = {
        "reported_missing_block": "Nao encontrei o bloco" in missing_text,
        "handler_escaped_to_agent_loop": missing_handler_escaped,
        "text_block_exists": bpy.data.texts.get("GN_Agent_Draft") is not None,
    }
    handle_write_script_draft({
        "block_name": "GN_Agent_Draft",
        "code": _valid_script(tree_name, "Restored base draft after missing-source validation"),
        "description": "Restored base draft after missing-source validation",
        "tree_name": tree_name,
    })

    class _RawCodeRuntime(_ValidationRuntime):
        def _agent_loop(self, *_args, **_kwargs):
            return _valid_script(tree_name, "Raw chat code should be redirected to Text Editor")

    raw_code_session = runtime.v1_session_for("")
    raw_code_session.execution_state.set_phase("drafting")
    raw_code_session.execution_state.current_draft = DraftedScript(
        block_name="GN_Agent_Draft_Raw_Leak",
        description="Raw code leak validation draft",
        tree_name=tree_name,
        version=1,
    )
    raw_code_ctx = TurnContext(
        session=raw_code_session,
        message="corrige esse draft",
        meta=ClassifierMeta(turn_class=TurnClass.DRAFT_WORKSPACE),
        blend_path="",
        _runtime=_RawCodeRuntime(),
        knowledge_dir=PROJECT_ROOT / "knowledge" / "domain",
    )
    raw_code_result = handle_workspace(raw_code_ctx, "focal_correction")
    raw_text_block = bpy.data.texts.get("GN_Agent_Draft_Raw_Leak")
    results["raw_chat_code_redirected_to_text_editor"] = {
        "response_has_import_bpy": "import bpy" in str(raw_code_result.response_text or ""),
        "text_block_exists": raw_text_block is not None,
        "text_block_chars": len(raw_text_block.as_string()) if raw_text_block is not None else 0,
        "reported_text_editor": "Text Editor" in str(raw_code_result.response_text or ""),
    }

    class _EconomyRetryRuntime(_ValidationRuntime):
        def __init__(self):
            super().__init__()
            self._session_state = {
                "tree_structural_memory": {
                    tree_name: {"tree_name": tree_name, "node_count": 12, "stale": False}
                }
            }

        def _block_draft_tool(self, tool_name, reason, policy):
            return f"BLOCKED: {tool_name} ({reason})"

        def _execute_tool(self, name, tool_input, _elapsed):
            block_reason = AgentRuntime._enforce_draft_tool_policy(self, name)
            if block_reason:
                raw = {"status": "blocked", "error": block_reason}
            elif name == "write_script_draft":
                raw = handle_write_script_draft(tool_input)
            elif name == "read_script_draft":
                raw = handle_read_script_draft(tool_input)
            else:
                raw = {"status": "success", "result": {"memory": {"node_count": 1, "tree_name": tree_name}}}
            payload = raw.get("result", {}) if isinstance(raw, dict) else {}
            self._current_turn_tools.append({
                "name": name,
                "input": tool_input,
                "result": json.dumps(raw, ensure_ascii=False)[:300],
                "status": str(raw.get("status", "")),
                "result_payload": payload if isinstance(payload, dict) else {},
            })
            return json.dumps(raw, ensure_ascii=False)

        def _agent_loop(self, *_args, **_kwargs):
            self._execute_tool("get_active_frame_context", {"tree_name": tree_name, "frame_name": "Metacarpos"}, 0)
            self._execute_tool("write_script_draft", {
                "block_name": "GN_Agent_Draft_Economy_Retry",
                "code": _valid_script(tree_name, "Economy retry validation"),
                "description": "Economy retry validation draft",
                "tree_name": tree_name,
            }, 0)
            return "feito"

    economy_session = runtime.v1_session_for("")
    economy_session.execution_state.set_phase("drafting")
    economy_session.execution_state.current_draft = DraftedScript(
        block_name="GN_Agent_Draft",
        description="Economy retry validation draft",
        tree_name=tree_name,
        version=1,
    )
    economy_session.execution_state.pending_draft_action = "write_confirmed_draft_revision"
    economy_session.execution_state.pending_draft_prompt = "Previous write failed; retry without investigation."
    economy_runtime = _EconomyRetryRuntime()
    economy_ctx = TurnContext(
        session=economy_session,
        message="consegue tentar denovo entao?",
        meta=ClassifierMeta(turn_class=TurnClass.DRAFT_WORKSPACE),
        blend_path="",
        _runtime=economy_runtime,
        knowledge_dir=PROJECT_ROOT / "knowledge" / "domain",
    )
    economy_result = handle_workspace(economy_ctx, "focal_correction")
    economy_statuses = {str(call.get("name")): str(call.get("status")) for call in economy_runtime._current_turn_tools}
    results["economy_retry_blocks_reads_and_writes"] = {
        "focal_read_status": economy_statuses.get("get_active_frame_context"),
        "write_status": economy_statuses.get("write_script_draft"),
        "reported_text_editor": "Text Editor" in str(economy_result.response_text or ""),
        "text_block_exists": bpy.data.texts.get("GN_Agent_Draft_Economy_Retry") is not None,
    }

    cases = {
        "A_meta": "VocÃª tem ideia do que eu pretendo fazer nessa Ã¡rvore biomodelo?",
        "B_correction": "corrige esse draft",
        "C_failure": "por que isso falhou?",
        "journal_control_z_failure": "Dei control+z, nao deu certo. Nenhum slider funcionou e a palma ainda sumiu",
        "journal_false_state_control": "dei ctrl+z denovo. Denovo ta sumindo o metacarpo 1 e agora a falange proximal 1 tbm. Nao faz nem sentido",
        "journal_short_confirmation": "Pode",
        "journal_retry_after_blocked_write": "consegue tentar denovo entao?",
    }
    results["router_cases"] = {}
    for key, message in cases.items():
        turn_class, meta, goal_mode = AgentRuntime._infer_turn_intent(session, message)
        results["router_cases"][key] = {
            "turn_class": turn_class.value,
            "goal_mode": goal_mode,
            "signals": list(meta.signals),
        }
        if turn_class == TurnClass.EXECUTION_FEEDBACK:
            outcome, reverted = _classify_execution_feedback(message)
            results["router_cases"][key]["feedback_outcome"] = outcome
            results["router_cases"][key]["reverted"] = reverted

    journal = OperationJournal(PROJECT_ROOT)
    journal.start_goal(user_message=cases["A_meta"], tree_name=tree_name, blend_file="")
    journal.log_runtime_event(
        event_type="session_memory_used",
        payload={"source": "draft_workspace", "has_goal": True, "has_hypothesis": True, "relevant_nodes_count": 2},
    )
    journal.log_runtime_event(
        event_type="script_draft_write_succeeded",
        payload={"turn_class": "draft_workspace", "block_name": "GN_Agent_Draft", "version": 1, "char_count": results["real_text_block_write"]["char_count"]},
    )
    journal.end_goal()
    dashboard = {}
    if journal.session_file and journal.session_file.exists():
        for line in journal.session_file.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            if entry.get("type") == "goal_end":
                dashboard = entry.get("dashboard", {})
    results["journal_dashboard"] = {
        "session_file": str(journal.session_file or ""),
        "session_memory_used": dashboard.get("session_memory_used"),
        "script_draft_write_succeeded_count": dashboard.get("script_draft_write_succeeded_count"),
    }

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    results["live_llm_cases"] = {"attempted": bool(api_key)}
    if api_key:
        try:
            agent = AgentRuntime(project_root=PROJECT_ROOT, api_key=api_key, runtime=runtime)
            live = {}
            for key, message in cases.items():
                text = agent.run_turn(message, blend_path="")
                live[key] = {
                    "response_preview": str(text or "")[:500],
                    "text_block_chars": len((bpy.data.texts.get("GN_Agent_Draft") or text_block).as_string()),
                }
            results["live_llm_cases"] = {"attempted": True, "ok": True, "cases": live}
        except Exception as exc:
            results["live_llm_cases"] = {"attempted": True, "ok": False, "error": str(exc)}

    failures: list[str] = []

    def expect(name: str, condition: bool) -> None:
        if not condition:
            failures.append(name)

    expect("partial_write_blocked", results["partial_write_blocked"].get("status") == "blocked")
    expect("real_text_block_write_success", results["real_text_block_write"].get("write_status") == "success")
    expect("real_text_block_read_success", results["real_text_block_write"].get("read_status") == "success")
    expect("real_text_block_exists", bool(results["real_text_block_write"].get("exists")))
    expect("real_text_block_valid_revision", results["real_text_block_write"].get("revision_validity") == "valid")
    expect(
        "inquiry_structural_discovery_single_read",
        results["inquiry_structural_discovery_smoke"].get("build_tree_structural_memory_calls") == 1,
    )
    expect(
        "inquiry_structural_discovery_has_nodes",
        int(results["inquiry_structural_discovery_smoke"].get("node_count") or 0) >= 2,
    )
    expect(
        "inquiry_prompt_contains_context_frame",
        bool(results["inquiry_structural_discovery_smoke"].get("contains_context_frame")),
    )
    expect(
        "inquiry_prompt_contains_validation_frame",
        bool(results["inquiry_structural_discovery_smoke"].get("contains_validation_frame")),
    )
    expect(
        "inquiry_refreshes_baseline_summary",
        bool(results["inquiry_structural_discovery_smoke"].get("baseline_has_summary")),
    )
    expect("handler_reports_blocked_write", bool(results["handler_blocked_write_not_success"].get("reported_blocked")))
    expect("missing_draft_source_reports_missing_block", bool(results["missing_draft_source_stops_early"].get("reported_missing_block")))
    expect("missing_draft_source_does_not_escape_to_agent_loop", not bool(results["missing_draft_source_stops_early"].get("handler_escaped_to_agent_loop")))
    expect("raw_chat_code_hidden_from_response", not bool(results["raw_chat_code_redirected_to_text_editor"].get("response_has_import_bpy")))
    expect("raw_chat_code_written_to_text_editor", bool(results["raw_chat_code_redirected_to_text_editor"].get("text_block_exists")))
    expect("raw_chat_code_reports_text_editor", bool(results["raw_chat_code_redirected_to_text_editor"].get("reported_text_editor")))
    expect("economy_retry_writes_text_block", bool(results["economy_retry_blocks_reads_and_writes"].get("text_block_exists")))
    expect("economy_retry_reports_text_editor", bool(results["economy_retry_blocks_reads_and_writes"].get("reported_text_editor")))
    expect("journal_dashboard_tracks_session_memory", bool(results["journal_dashboard"].get("session_memory_used")))
    expect(
        "journal_dashboard_counts_script_write",
        int(results["journal_dashboard"].get("script_draft_write_succeeded_count") or 0) >= 1,
    )
    if results["live_llm_cases"].get("attempted"):
        expect("live_llm_cases_ok", bool(results["live_llm_cases"].get("ok")))

    results["ok"] = not failures
    results["validation_failures"] = failures
    report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("VALIDATION_REPORT=" + str(report_path))
    print(json.dumps(results, ensure_ascii=False))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

