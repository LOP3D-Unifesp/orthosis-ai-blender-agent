# PHASE7_NOTES.md — One-Shot Failure Policy

> Phase 7 of REFATOR_PLAN.md — Workstream F
> Implemented: 2026-04-07

---

## What Phase 7 is

Enforce the one-shot explain-and-stop failure policy end-to-end:

- After one failed mutation attempt: stop, explain, return control to the user.
- No automatic replan loop. No new approval gate. No retry counter.
- Phase transitions: `executing → failed → idle` (via user message, never automatic).

---

## What changed

### 1. `blender_addon/agent_runtime.py` — BASE_SYSTEM_PROMPT

Two rules were directly contradicting Phase 7 policy:

```
# BEFORE (wrong — told model to replan and request dedicated approval):
- If a mutation fails, stop, replan, and request fresh approval.
- If execute_code fallback is proposed, make that explicit and request dedicated approval.

# AFTER (correct — one-shot, explain-and-stop):
- If a mutation fails, stop immediately, explain what was tried and what failed,
  and return control to the user. No automatic replan. No new approval gate.
```

The model now knows it must never propose replanning or a new approval gate after failure.

### 2. `blender_addon/session/schema.py` — ExecutionState

Removed `consecutive_failures: int = 0` field. This field implied retry semantics that Phase 7 explicitly prohibits. Changes:

- Field deleted from the dataclass.
- Removed from `to_dict()`.
- `from_dict()` silently ignores `consecutive_failures` if present in older serialised sessions (backward-compat on load, forward-clean on write).

### 3. `blender_addon/session/store.py` — `_build_execution_state_from_legacy()`

The legacy-migration helper was still passing `consecutive_failures=0` to the `ExecutionState` constructor. Removed that keyword argument.

### 4. `blender_addon/runtime/core.py` — three dead assignments removed

The legacy-state mirror path in `_sync_v1_session` / `_apply_tool_result_to_v1_session` had three stale assignments:

```python
session.execution_state.consecutive_failures = 0   # on normal state
session.execution_state.consecutive_failures = 1   # on failure mirror
session.execution_state.consecutive_failures = 1   # in _apply_tool_result_to_v1_session
```

All three removed.

---

## What did NOT need to change

The handler layer was already correct from Phase 3/4:

- `mutation_confirmation.py` — already implements explain-and-stop via `_on_failure()`.
  No replan. No retry. Records `LastFailure`, clears pending, calls `_sm.mark_failed()`.
- `post_failure_recovery.py` — already resets to idle via `_sm.reset()`. No replan proposal.
- `state_machine.py` — already has no replan/retry transition from `failed`. Only valid
  exit from `failed` is `reset → idle`.
- Tombstoned modules (`execution_postprocess`, `runtime_execution`, `execution_prechecks`,
  `runtime_governance`) — already raise `ImportError` on access (Phase 5 tombstones).

---

## Tests

### Updated tests

- `tests/test_session_schema_v1.py` — removed stale `consecutive_failures == 0` assertion.
- `tests/test_turn_router_phase3.py` — removed `consecutive_failures=0` from session stub.

### New test file

`tests/test_failure_policy_phase7.py` — 27 tests across 6 classes:

| Class | What it tests |
|---|---|
| `TestStateMachineFailurePolicy` | No replan event exists; `failed → idle` only via reset; `mark_failed` works |
| `TestRouterFailureGating` | Every message routes to `POST_FAILURE_RECOVERY` when `phase == failed` |
| `TestMutationConfirmationFailurePolicy` | Failure sets `phase=failed`, records `LastFailure`, clears pending, no replan text |
| `TestPostFailureRecoveryHandler` | Resets to idle, returns explanation, no replan proposal |
| `TestConsecutiveFailuresRemoved` | Field absent from `ExecutionState`, `to_dict()`, and `from_dict()` |
| `TestSystemPromptFailurePolicy` | Prompt has no "stop, replan", no "dedicated approval", has "No automatic replan" |
| `TestTombstoneGuardsPhase7` | Tombstoned replan modules raise `ImportError` |

### Test results after Phase 7

```
Ran 258 tests in ~0.3s
FAILED (errors=1, skipped=2)
```

- **1 pre-existing error**: `test_context_knowledge` — Phase 6 tombstone (not caused by Phase 7).
- **2 pre-existing skips**: unchanged.
- **All 27 Phase 7 tests**: PASS.

---

## Legacy replan surfaces deferred to Phase 8+

The following references to failure/replan concepts are in non-runtime files and were
intentionally left untouched (no live effect on policy):

| File | Detail |
|---|---|
| `operation_journal.py` | Event log may record old event names — read-only audit trail |
| `session_store.py` | Flat-dict legacy fields (already handled in migration path above) |
| `chat_ui.py` | Any UI text referencing old error display — UI layering is Phase 9 scope |
| `REFATOR_PLAN.md` | Source-of-truth document — not modified |

---

## Invariants now enforced

1. `phase == failed` → router sends every message to `POST_FAILURE_RECOVERY` exclusively.
2. `StateMachine` has no `replan` event and no transition out of `failed` except `reset`.
3. `ExecutionState` has no `consecutive_failures` field (no retry counter exists).
4. `BASE_SYSTEM_PROMPT` tells the model "No automatic replan" explicitly.
5. `mutation_confirmation` returns `phase_transition="failed"` and includes the error — never replan text.
6. `post_failure_recovery` returns `phase_transition="idle"` — always terminates the failure arc.
