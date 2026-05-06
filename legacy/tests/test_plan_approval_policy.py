"""test_plan_approval_policy.py — RETIRED in Phase 4 of REFATOR_PLAN.md.

The functions this file tested (``recover_inconsistent_state``,
approval-token helpers from ``runtime_governance``) were removed in Phase 4.

Approval behaviour is now covered by ``tests/test_approval_phase4.py``
(phase-based authorization, StateMachine transitions, confirmation flow).
"""

import unittest


class RetiredPlanApprovalPolicyTests(unittest.TestCase):
    """Placeholder so the test runner does not error on an empty file."""

    def test_retired(self) -> None:
        self.skipTest(
            "test_plan_approval_policy retired in Phase 4 — see test_approval_phase4.py"
        )
