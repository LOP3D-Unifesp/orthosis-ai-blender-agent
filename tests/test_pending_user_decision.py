from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


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
    def __init__(self) -> None:
        self.journal = _Journal()
        self._session_state = {"turn_counter": 10}


class PendingUserDecisionTests(unittest.TestCase):
    def test_old_session_loads_with_no_pending_decision(self) -> None:
        from blender_addon.session.schema import Session

        payload = Session.new("old.blend").to_dict()
        payload["execution_state"].pop("pending_user_decision", None)

        restored = Session.from_dict(payload)

        self.assertIsNone(restored.execution_state.pending_user_decision)

    def test_pending_decision_round_trips_through_session_payload(self) -> None:
        from blender_addon.runtime.pending_decision import set_pending_decision
        from blender_addon.session.schema import Session

        session = Session.new("case.blend")
        ctx = SimpleNamespace(session=session, _runtime=_Runtime())

        set_pending_decision(
            ctx,
            kind="strategy_choice",
            options=["A", "B"],
            prompt_summary="Qual caminho?",
            source_revision=12,
            related_failure="executed_no_effect",
        )
        payload = json.loads(json.dumps(session.to_dict(), ensure_ascii=False))
        restored = Session.from_dict(payload)

        decision = restored.execution_state.pending_user_decision
        self.assertIsNotNone(decision)
        self.assertEqual("pending", decision.status)
        self.assertEqual(["A", "B"], decision.options)
        self.assertEqual(12, decision.source_revision)

    def test_session_file_replace_retries_brief_permission_error(self) -> None:
        from blender_addon.session import store

        calls = {"count": 0}
        replaced = {"done": False}
        original_sleep = store.time.sleep

        class _FlakySource:
            def replace(self, _dst) -> None:
                calls["count"] += 1
                if calls["count"] == 1:
                    raise PermissionError("temporarily locked")
                replaced["done"] = True

        try:
            store.time.sleep = lambda _seconds: None
            store._replace_with_retry(_FlakySource(), object())
        finally:
            store.time.sleep = original_sleep

        self.assertEqual(2, calls["count"])
        self.assertTrue(replaced["done"])

    def test_option_phrases_resolve_against_closed_options(self) -> None:
        from blender_addon.runtime.pending_decision import resolve_pending_decision, set_pending_decision
        from blender_addon.session.schema import Session

        for message in ("Caminho B", "vou pela B", "sim, a segunda", "manda a B", "opcao B"):
            session = Session.new("case.blend")
            ctx = SimpleNamespace(session=session, _runtime=_Runtime())
            set_pending_decision(ctx, kind="strategy_choice", options=["A", "B"], prompt_summary="A ou B?")

            result = resolve_pending_decision(session, message, runtime=ctx._runtime)

            self.assertEqual("answered", result.status, message)
            self.assertEqual("B", result.answered_with)
            self.assertEqual("answered", session.execution_state.pending_user_decision.status)
            self.assertEqual("B", session.execution_state.pending_user_decision.answered_with)
            self.assertEqual("STRATEGY_APPROVED", session.execution_state.session_state)

    def test_question_keeps_pending_even_when_it_mentions_option(self) -> None:
        from blender_addon.runtime.pending_decision import resolve_pending_decision, set_pending_decision
        from blender_addon.session.schema import Session

        session = Session.new("case.blend")
        runtime = _Runtime()
        set_pending_decision(
            SimpleNamespace(session=session, _runtime=runtime),
            kind="strategy_choice",
            options=["A", "B"],
            prompt_summary="A ou B?",
        )

        result = resolve_pending_decision(session, "mas por que a B?", runtime=runtime)

        self.assertEqual("pending", result.status)
        self.assertTrue(result.question)
        self.assertEqual("pending", session.execution_state.pending_user_decision.status)

    def test_ambiguous_affirmative_does_not_choose_side(self) -> None:
        from blender_addon.runtime.pending_decision import resolve_pending_decision, set_pending_decision
        from blender_addon.session.schema import Session

        session = Session.new("case.blend")
        runtime = _Runtime()
        set_pending_decision(
            SimpleNamespace(session=session, _runtime=runtime),
            kind="strategy_choice",
            options=["A", "B"],
            prompt_summary="A ou B?",
        )

        result = resolve_pending_decision(session, "vamos lá", runtime=runtime)

        self.assertEqual("pending", result.status)
        self.assertTrue(result.needs_clarification)
        self.assertEqual("pending", session.execution_state.pending_user_decision.status)
        self.assertEqual("", session.execution_state.pending_user_decision.answered_with)

    def test_repair_direction_accepts_clear_yes_and_cancels_no(self) -> None:
        from blender_addon.runtime.pending_decision import resolve_pending_decision, set_pending_decision
        from blender_addon.session.schema import Session

        session = Session.new("case.blend")
        runtime = _Runtime()
        set_pending_decision(
            SimpleNamespace(session=session, _runtime=runtime),
            kind="repair_direction",
            options=["sim", "não"],
            prompt_summary="Quer que eu siga por essa direção?",
        )

        result = resolve_pending_decision(session, "pode seguir", runtime=runtime)

        self.assertEqual("answered", result.status)
        self.assertEqual("sim", result.answered_with)
        self.assertEqual("STRATEGY_APPROVED", session.execution_state.session_state)

        session = Session.new("case.blend")
        set_pending_decision(
            SimpleNamespace(session=session, _runtime=runtime),
            kind="repair_direction",
            options=["sim", "não"],
            prompt_summary="Quer que eu siga por essa direção?",
        )

        result = resolve_pending_decision(session, "não", runtime=runtime)

        self.assertEqual("cancelled", result.status)
        self.assertEqual("cancelled", session.execution_state.pending_user_decision.status)

    def test_repair_direction_strategy_language_resolves_to_single_positive(self) -> None:
        # "caminho B" with options=["sim","não"]: only 1 positive path → resolve to "sim".
        # Old behaviour (needs_clarification) was confusing UX — the user is clearly approving.
        from blender_addon.runtime.pending_decision import resolve_pending_decision, set_pending_decision
        from blender_addon.session.schema import Session

        for phrase in ("caminho B", "opção A", "estrategia A", "vou pelo caminho B"):
            session = Session.new("case.blend")
            runtime = _Runtime()
            set_pending_decision(
                SimpleNamespace(session=session, _runtime=runtime),
                kind="repair_direction",
                options=["sim", "não"],
                prompt_summary="Quer que eu siga por essa direção?",
            )

            result = resolve_pending_decision(session, phrase, runtime=runtime)

            self.assertEqual("answered", result.status, f"phrase={phrase!r}")
            self.assertEqual("sim", result.answered_with, f"phrase={phrase!r}")
            self.assertEqual("STRATEGY_APPROVED", session.execution_state.session_state, f"phrase={phrase!r}")

    def test_confirmo_resolves_repair_direction(self) -> None:
        # "confirmo" with options=["sim","não"] → resolved to "sim".
        from blender_addon.runtime.pending_decision import resolve_pending_decision, set_pending_decision
        from blender_addon.session.schema import Session

        for phrase in ("confirmo", "confirmado", "certo", "claro", "pode", "ok", "sim"):
            session = Session.new("case.blend")
            runtime = _Runtime()
            set_pending_decision(
                SimpleNamespace(session=session, _runtime=runtime),
                kind="repair_direction",
                options=["sim", "não"],
                prompt_summary="Quer que eu siga por essa direção?",
            )

            result = resolve_pending_decision(session, phrase, runtime=runtime)

            self.assertEqual("answered", result.status, f"phrase={phrase!r}")
            self.assertEqual("sim", result.answered_with, f"phrase={phrase!r}")

    def test_confirmo_with_two_options_triggers_clarification(self) -> None:
        # "confirmo" with options=["A","B"] → 2 positive paths → clarification needed.
        from blender_addon.runtime.pending_decision import resolve_pending_decision, set_pending_decision
        from blender_addon.session.schema import Session

        for phrase in ("confirmo", "pode", "ok", "sim"):
            session = Session.new("case.blend")
            runtime = _Runtime()
            set_pending_decision(
                SimpleNamespace(session=session, _runtime=runtime),
                kind="strategy_choice",
                options=["A", "B"],
                prompt_summary="A ou B?",
            )

            result = resolve_pending_decision(session, phrase, runtime=runtime)

            self.assertEqual("pending", result.status, f"phrase={phrase!r}")
            self.assertTrue(result.needs_clarification, f"phrase={phrase!r}")
            self.assertEqual("pending", session.execution_state.pending_user_decision.status)

    def test_read_authorization_yes_does_not_schedule_write(self) -> None:
        from blender_addon.runtime.pending_decision import resolve_pending_decision, set_pending_decision
        from blender_addon.runtime.routing_obs import infer_turn_intent
        from blender_addon.session.schema import Session

        session = Session.new("case.blend")
        runtime = _Runtime()
        set_pending_decision(
            SimpleNamespace(session=session, _runtime=runtime),
            kind="read_authorization",
            options=["sim", "não"],
            prompt_summary="Posso fazer uma leitura focal?",
        )

        result = resolve_pending_decision(session, "sim", runtime=runtime)

        self.assertEqual("answered", result.status)
        self.assertEqual("sim", result.answered_with)
        self.assertEqual("", session.execution_state.pending_draft_action)
        self.assertNotEqual("STRATEGY_APPROVED", session.execution_state.session_state)
        self.assertNotEqual("strategy_approval", infer_turn_intent(session, "sim", [], "context_inquiry"))

    def test_strategy_proposed_does_not_collapse_while_pending(self) -> None:
        from blender_addon.runtime.pending_decision import set_pending_decision
        from blender_addon.session import compute_next_state
        from blender_addon.session.schema import Session

        session = Session.new("case.blend")
        es = session.execution_state
        es.session_state = "STRATEGY_PROPOSED"
        es.retry_requires_draft_change = True
        set_pending_decision(
            SimpleNamespace(session=session, _runtime=_Runtime()),
            kind="strategy_choice",
            options=["A", "B"],
            prompt_summary="A ou B?",
        )

        self.assertEqual("STRATEGY_PROPOSED", compute_next_state(session))

    def test_resolution_does_not_add_open_phrases_to_router_lists(self) -> None:
        routing_obs = (PROJECT_ROOT / "blender_addon" / "runtime" / "routing_obs.py").read_text(encoding="utf-8")
        router = (PROJECT_ROOT / "blender_addon" / "runtime" / "router.py").read_text(encoding="utf-8")
        for forbidden in ("vou pela b", "caminho b", "opcao b", "opção b", "sim, a segunda"):
            self.assertNotIn(forbidden, routing_obs.lower())
            self.assertNotIn(forbidden, router.lower())

    def test_console_help_fast_path_avoids_workspace_tools(self) -> None:
        from blender_addon.fast_path import try_fast_path
        from blender_addon.session.schema import Session

        runtime = _Runtime()
        hit = try_fast_path("onde eu vejo o que o console imprimiu?", session=Session.new("case.blend"), runtime=runtime)

        self.assertIsNotNone(hit)
        text, meta = hit
        self.assertEqual("blender_console_help", meta["fp_type"])
        self.assertIn("Window > Toggle System Console", text)


if __name__ == "__main__":
    unittest.main()
