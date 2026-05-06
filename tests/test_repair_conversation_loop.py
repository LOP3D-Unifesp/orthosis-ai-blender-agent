from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if "bpy" not in sys.modules:
    sys.modules["bpy"] = SimpleNamespace(
        data=SimpleNamespace(filepath=""),
        app=SimpleNamespace(
            handlers=SimpleNamespace(
                persistent=lambda fn: fn,
                load_post=[],
                save_post=[],
            )
        ),
    )


class _Journal:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def log_runtime_event(self, event_type: str, payload: dict | None = None, status: str = "info") -> None:
        self.events.append({"event_type": event_type, "payload": payload or {}, "status": status})


class _Runtime:
    def __init__(self, response: str) -> None:
        self._messages = [{"role": "assistant", "content": "old"}]
        self._session_state = {
            "turn_counter": 3,
            "tree_structural_memory": {
                "tree_name": "Biomodelo_GN",
                "node_count": 3,
                "nodes": [
                    {"name": "TF_Metacarpo1.001", "parent_frame": "Metacarpos"},
                    {"name": "TF_Metacarpo2", "parent_frame": "Falanges1"},
                    {"name": "Group Input", "parent_frame": ""},
                ],
            },
        }
        self.response = response
        self.tool_calls: list[str] = []
        self.last_prompt = ""
        self.journal = _Journal()

    def _execute_tool(self, name, tool_input, _elapsed):
        self.tool_calls.append(name)
        if name == "read_script_draft":
            return json.dumps({
                "status": "success",
                "result": {
                    "block_name": "GN_Agent_Draft",
                    "version": 4,
                    "content": "# live draft should not be used",
                    "char_count": 32,
                },
            })
        return json.dumps({"status": "success", "result": {"memory": self._session_state["tree_structural_memory"]}})

    def _request_text_response(self, *, system, messages, max_tokens):
        content = messages[0]["content"]
        self.last_prompt = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        return self.response


def _session_with_failed_draft():
    from blender_addon.session.schema import Session

    session = Session.new("case.blend")
    es = session.execution_state
    es.current_draft = SimpleNamespace(
        block_name="GN_Agent_Draft",
        tree_name="Biomodelo_GN",
        version=4,
        last_written_chars=120,
    )
    es.draft_block_name = "GN_Agent_Draft"
    return session


def _ctx(session, runtime, message="Rodei e mexeu falange, nada a ver. Reverti."):
    from blender_addon.runtime.handlers import TurnContext
    from blender_addon.runtime.router import ClassifierMeta, TurnClass

    return TurnContext(
        session=session,
        message=message,
        meta=ClassifierMeta(turn_class=TurnClass.EXECUTION_FEEDBACK),
        blend_path="",
        _runtime=runtime,
        knowledge_dir=Path("/nonexistent/knowledge/domain"),
    )


def _archived_draft():
    return {
        "block_name": "GN_Agent_Draft",
        "content": (
            "nodes = tree.nodes\n"
            "mc1_tf = nodes.get('TF_Metacarpo1.001')\n"
            "mc2_tf = nodes.get('TF_Metacarpo2')\n"
            "disconnect_translation(mc2_tf)\n"
            "mc2_tf.inputs['Translation'].default_value = (1, 0, 0)\n"
            "print('Nenhuma falange alterada')\n"
        ),
        "version": 4,
        "char_count": 220,
        "draft_archive_path": "runtime/draft_history/sess/r000004_GN_Agent_Draft.py",
        "source": "draft_history",
    }


class RepairConversationLoopTests(unittest.TestCase):
    def test_post_failure_handler_sets_pending_decision_for_ab_options(self) -> None:
        from blender_addon.runtime.handlers.drafting import handle_execution_feedback

        response = (
            "O conflito central é: draft claims no falanges changed, but touched nodes/frames include "
            "falange-related names. Isso aponta para o alvo errado.\n"
            "A. Isolar o mismatch.\n"
            "B. Reescrever a região afetada.\n"
            "Qual caminho?"
        )
        session = _session_with_failed_draft()
        runtime = _Runtime(response)

        with patch("blender_addon.runtime.handlers.drafting._read_archived_draft_revision", return_value=_archived_draft()):
            result = handle_execution_feedback(_ctx(session, runtime))

        decision = session.execution_state.pending_user_decision
        self.assertIsNotNone(decision)
        self.assertEqual("pending", decision.status)
        self.assertEqual(["A", "B"], decision.options)
        self.assertEqual("strategy_choice", decision.kind)
        self.assertEqual("STRATEGY_PROPOSED", session.execution_state.session_state)
        self.assertIn("só vou escrever uma nova revisão depois dessa confirmação", result.response_text)
        self.assertTrue(any(e["event_type"] == "pending_decision_proposed" for e in runtime.journal.events))

    def test_static_evidence_mismatch_forces_fallback_to_use_real_mismatch(self) -> None:
        from blender_addon.runtime.handlers.drafting import handle_execution_feedback

        generic = (
            "Pode ser problema de sockets ou links.\n"
            "A. Ajustar sockets.\n"
            "B. Recriar links.\n"
            "Qual caminho?"
        )
        session = _session_with_failed_draft()
        runtime = _Runtime(generic)

        with patch("blender_addon.runtime.handlers.drafting._read_archived_draft_revision", return_value=_archived_draft()):
            result = handle_execution_feedback(_ctx(session, runtime))

        self.assertIn("draft claims no falanges changed, but touched nodes/frames include falange-related names", result.response_text)
        self.assertIn("Quer que eu siga por essa direção", result.response_text)
        self.assertEqual(["sim", "não"], session.execution_state.pending_user_decision.options)
        self.assertEqual("repair_direction", session.execution_state.pending_user_decision.kind)
        payload = [e for e in runtime.journal.events if e["event_type"] == "script_draft_execution_diagnosis"][-1]["payload"]
        self.assertFalse(payload["diagnosis_missing_sections"])
        self.assertTrue(payload["diagnosis_contract_satisfied"])

    def test_fallback_varies_with_evidence(self) -> None:
        from blender_addon.runtime.handlers.drafting import _fallback_post_failure_diagnosis

        first = _fallback_post_failure_diagnosis(
            block_name="GN_Agent_Draft",
            revision=1,
            content="",
            outcome="executed_failed",
            notes="falhou",
            structural_memory={},
            failed_draft_source="draft_history",
            reverted=False,
            evidence={"semantic_mismatches": ["draft claims no falanges changed, but touched nodes/frames include falange-related names"]},
        )
        second = _fallback_post_failure_diagnosis(
            block_name="GN_Agent_Draft",
            revision=2,
            content="",
            outcome="executed_failed",
            notes="falhou",
            structural_memory={},
            failed_draft_source="draft_history",
            reverted=False,
            evidence={"semantic_mismatches": ["TF_X name suggests metacarpo but parent_frame=Falanges label=? suggests falange"]},
        )

        self.assertNotEqual(first, second)
        self.assertIn("falanges changed", first)
        self.assertIn("TF_X", second)

    def test_static_evidence_detects_socket_alias_component_writes(self) -> None:
        from blender_addon.runtime.handlers.drafting import _extract_failed_draft_static_evidence

        code = (
            "nodes = tree.nodes\n"
            "tf_a = nodes.get('TF_Metacarpo1.001')\n"
            "tf_b = nodes.get('TF_Metacarpo2')\n"
            "sk_a = get_translation_socket(tf_a)\n"
            "sk_b = find_translation_input(tf_b)\n"
            "sk_a.default_value[0] = -half\n"
            "sk_b.default_value[0] = +half\n"
        )

        evidence = _extract_failed_draft_static_evidence(code, {})

        self.assertEqual(["TF_Metacarpo1.001", "TF_Metacarpo2"], evidence["touched_nodes"])
        self.assertIn({"node": "TF_Metacarpo1.001", "socket": "Translation"}, evidence["socket_writes"])
        self.assertEqual(2, evidence["counts"]["default_value_writes"])

    def test_minimum_useful_analysis_does_not_fabricate_ab(self) -> None:
        from blender_addon.runtime.handlers.drafting import _minimum_useful_analysis_response

        response = _minimum_useful_analysis_response(
            block_name="GN_Agent_Draft",
            revision=31,
            content="sk_a.default_value[0] = -half",
            outcome="executed_failed",
            notes="nao aconteceu nada",
            structural_memory={},
        )

        self.assertNotIn("Strategy A", response)
        self.assertNotIn("Strategy B", response)
        self.assertIn("Direcao de reparo", response)


if __name__ == "__main__":
    unittest.main()
