# PHASE3_NOTES.md

> Phase 3 of `REFATOR_PLAN.md` — Turn Router and Handlers (Workstream C).
> Status: complete for Phase 3 scope. The system remains runnable.
> Verification: `python -m unittest discover -s tests` → 141 tests (139 pass, 1 skip, 1 pre-existing error).

---

## What changed

### 1. `runtime/router.py` — `TurnRouter` + `TurnClass`

The `TurnRouter` classifier maps every incoming message to exactly one of
nine turn classes without making an LLM call:

| TurnClass | Primary signals |
|---|---|
| `greeting_or_smalltalk` | Greeting / thanks patterns |
| `clarification` | Default fallback (safest) |
| `diagnosis` | Interrogative / read-intent patterns |
| `baseline_refresh` | Explicit rebuild/refresh request |
| `proposal` | "how would you…", "suggest…" patterns |
| `mutation_request` | Imperative change patterns ("set", "change", "wire…") |
| `mutation_confirmation` | Phase gated: `awaiting_confirmation` + affirmative |
| `mutation_denial` | Phase gated: `awaiting_confirmation` + negative |
| `post_failure_recovery` | Phase gated: `failed` → any input |

Classification priority order (§8.2 of `REFATOR_PLAN.md`):
1. Phase-gated: `awaiting_confirmation` / `failed` take absolute priority.
2. Trivial social patterns → `greeting_or_smalltalk`.
3. Explicit baseline-refresh request.
4. Proposal patterns (wins over mutation when both fire — less risky class).
5. Mutation (imperative) patterns.
6. Diagnosis (interrogative/read) patterns.
7. Default: `clarification`.

`ClassifierMeta` carries: `turn_class`, `confidence`, `signals`,
`needs_baseline_refresh`, and the `raw_message` for handler use.

### 2. `runtime/state_machine.py` — `StateMachine`

Owns every `execution_state.phase` transition.  Nothing outside this module
sets the phase directly; callers call `sm.transition(session, event)` or
typed helpers (`propose_mutation`, `confirm`, `deny`, `mark_succeeded`,
`mark_failed`, `reset`).

Transition table covers the full 7-phase set:
`idle | reading | proposing | awaiting_confirmation | executing | failed | halted`

`halt_requested` is a wildcard event that applies from any phase.
Invalid transitions raise `InvalidTransitionError` — no silent no-ops.

### 3. `runtime/handlers/` — nine turn handlers

Package layout:
```
runtime/handlers/
├── __init__.py          HandlerResult, TurnContext, dispatch_turn
├── greeting.py          Fixed replies for common greetings; API call for others
├── clarification.py     Single text call, no mutation tools
├── diagnosis.py         Read tools only; auto-refreshes stale baseline
├── baseline_refresh.py  Reads full tree; updates session.baseline_workspace
├── proposal.py          Reads + reasoned response; no mutation tools
├── mutation_request.py  Computes change, stores PendingMutation, → awaiting_confirmation
├── mutation_confirmation.py  Executes pending mutation, single attempt, no retry
├── mutation_denial.py   No API call; clears pending, → idle
└── post_failure_recovery.py  Explain-and-stop; resets phase to idle
```

Handler contract (§8.3):
```
input:  TurnContext {session, message, meta, _runtime, ...}
output: HandlerResult {response_text, tool_calls_made, phase_transition, session_mutations}
```

`TurnContext` is the dependency boundary.  Handlers use its typed helpers
(`call_agent_loop`, `request_text`, `execute_tool`, `log_event`) and never
reach into `_runtime` private attributes directly.

### 4. `runtime/prompt_builder.py` — compact system prompts

Replaces the 4×1400 + 4×1200 token knowledge dump from
`context_prompt.build_system_prompt` (item 18 of the "Do Not Preserve" list).

Budget: ≤1550 tokens without knowledge, ≤2500 with a small knowledge bundle.

Structure:
1. **Base role block** (~250 tokens) — Blender GN copilot identity + core rules.
2. **Focus + baseline block** (~200 tokens) — focused tree name, baseline state.
3. **State hint** — one-line note if `awaiting_confirmation` or `failed`.
4. **Turn-class guidance** (~100 tokens) — specific instruction for this turn.
5. **Knowledge bundle** (≤1000 tokens) — caller-supplied, pre-selected items.

### 5. `agent_runtime.run_turn` — new router-based entry point

`AgentRuntime.run_turn` no longer calls `execute_turn` from `runtime_turn.py`.
The new flow:

```
run_turn(message)
  → reset per-turn state
  → load legacy state (compat: tools still read self._session_state)
  → load v1 session (primary from Phase 3)
  → TurnRouter.classify(session, message)
  → if awaiting_confirmation_override: clear pending + re-classify
  → build TurnContext
  → dispatch_turn(turn_class, ctx)
  → update session history (v1)
  → bump turn_counter (legacy)
  → save v1 session (primary)
  → _sync_v1_to_legacy (mirror to flat dict for compat)
  → maybe_extract_knowledge (background)
  → return result.response_text
```

The 12-stage pipeline is gone.  The flag constants (`ALWAYS_PLAN_FIRST`,
`MUTATION_REQUIRES_USER_APPROVAL`, `REPLAN_AFTER_FAILURE`,
`CODE_FALLBACK_REQUIRES_NEW_APPROVAL`) are no longer consulted by `run_turn`.

### 6. `runtime_turn.py` — tombstone

The file now raises `ImportError` immediately on import with a clear message
directing callers to `AgentRuntime.run_turn`.  Any remaining import of
`run_turn` from `runtime_turn` is a stale reference that must be removed.

### 7. `tests/test_agent_routing.py` — retired

The tests in this file tested `_rehydrate_message_after_chat_plan_action` and
`_should_treat_as_pending_context_reply` from the deleted pipeline.  The file
now contains a single skipped placeholder test pointing to
`test_turn_router_phase3.py` for equivalent coverage.

### 8. `tests/test_turn_router_phase3.py` — new test suite

26 new tests covering:
* `TurnRouter.classify`: phase-gated routing, all 9 signal classes, stale-baseline detection.
* `StateMachine`: every valid transition, invalid transition raises, wildcard halt, all typed helpers.
* `PromptBuilder`: token budget, focus block, turn guidance for all 9 classes, knowledge rendering.
* Handler unit tests (`mutation_denial`, `greeting`) that require no live API.

---

## Compatibility layers still remaining

These are intentional Phase 3 holdovers:

* `RuntimeBridgeCore = Runtime` alias in `blender_addon/server.py`.
* Legacy `SessionStore` and `runtime/sessions/` still present and loaded in
  `run_turn` for tool-execution compat (`self._session_state`).
* `_sync_v1_to_legacy` mirrors v1 changes back to the flat dict every turn
  so `chat_ui.py` and socket callers remain functional.
* The helper imports at the top of `agent_runtime.py` (runtime_planning,
  runtime_governance, runtime_execution, etc.) are still present — they are
  used by `_execute_tool`, `_detect_intent`, and other methods that handlers
  call indirectly via `TurnContext`. These will be cleaned up in Phase 5
  (Dispatcher Consolidation).

---

## What remains for Phase 4

Phase 4 should start from this state:

* Wire approval entirely through `execution_state.phase` and delete the
  approval-token / plan-token fields from the session.
* Delete `_EXECUTION_RESUME_KEYWORDS`, plan/approval token generation,
  `_render_plan_approval_message`, `_request_conversational_plan_response`.
* Delete the precheck cascade in `execution_prechecks.py`.
* Remove the legacy keyword-approval constants from `agent_runtime.py`
  (`ALWAYS_PLAN_FIRST`, `MUTATION_REQUIRES_USER_APPROVAL`,
  `REPLAN_AFTER_FAILURE`, `CODE_FALLBACK_REQUIRES_NEW_APPROVAL`).
* Tests: every state-machine transition rule, every invalidation rule.

Out of scope for Phase 3 (not started):
* Approval token deletion (Phase 4).
* Dispatcher consolidation (Phase 5).
* Knowledge retriever (Phase 6).
* Failure policy (Phase 7).
* UI layering (Phase 8).
* MCP cleanup (Phase 9).
