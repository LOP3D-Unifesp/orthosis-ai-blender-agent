"""test_agent_routing.py — RETIRED in Phase 3 of REFATOR_PLAN.md.

The helpers this file tested (``_rehydrate_message_after_chat_plan_action``,
``_should_treat_as_pending_context_reply``) lived in ``runtime_turn.py`` as
part of the 12-stage pipeline.  That pipeline was deleted in Phase 3.

Routing behaviour is now covered by ``tests/test_turn_router_phase3.py``
(TurnRouter, StateMachine, PromptBuilder tests).
"""

import unittest


class RetiredAgentRoutingTests(unittest.TestCase):
    """Placeholder so the test runner does not error on an empty file."""

    def test_retired(self) -> None:
        self.skipTest(
            "test_agent_routing retired in Phase 3 — see test_turn_router_phase3.py"
        )
