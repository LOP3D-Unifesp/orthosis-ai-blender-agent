"""Handler: post_failure_recovery.

The last execution failed (phase == "failed") and the user has sent a
message.  The handler explains what went wrong, suggests an alternative if
one is obvious, and resets the phase to idle so the user can continue.

No replan loop.  No automatic retry.  One explain-and-stop response only
(§8.6 and item 9 of the "Do Not Preserve" list in REFATOR_PLAN.md).
"""

from __future__ import annotations

from . import HandlerResult, TurnContext
from ..prompt_builder import build_system_prompt
from ..state_machine import StateMachine

_sm = StateMachine()


def handle(ctx: TurnContext) -> HandlerResult:
    session = ctx.session
    last_failure = session.execution_state.last_failure

    knowledge = ctx.retrieve_knowledge()
    system = build_system_prompt(session, "post_failure_recovery", knowledge=knowledge)
    messages = ctx.build_messages()

    # Add the failure context to the system prompt so the model can explain it.
    if last_failure:
        failure_note = (
            f"\n\nMost recent failure:\n"
            f"  Tool: {last_failure.tool}\n"
            f"  Error: {last_failure.error[:300]}\n"
            f"  Cause: {last_failure.cause}"
        )
        if last_failure.suggested_alternative:
            failure_note += f"\n  Suggested alternative: {last_failure.suggested_alternative}"
        system = system + failure_note

    text = ctx.call_agent_loop(system, messages)

    # Reset to idle: user can now send a new request.
    _sm.reset(session)

    return HandlerResult(
        response_text=text,
        phase_transition="idle",
        session_mutations=[{"type": "failure_recovery_completed"}],
    )
