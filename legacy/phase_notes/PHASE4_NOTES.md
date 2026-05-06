# PHASE4_NOTES.md

> Phase 4 of `REFATOR_PLAN.md` — Approval Wiring (Workstream D).
> Status: complete for Phase 4 scope. The system remains runnable.
> Verification: `python -m unittest discover -s tests` → 152 tests (149 pass, 2 skip, 1 pre-existing error).

---

## What changed

### 1. `agent_runtime.py` — Phase 4 `_execute_tool`

The old `_execute_tool` called `runtime_execution.execute_tool()` which orchestrated a
6-gate precheck cascade via `execution_prechecks.py`.  That cascade blocked every mutation
tool call from Phase 3 handlers because `ensure_mutation_approval_pre_dispatch` checked for
a legacy `approval_token` that handlers never set.

**Phase 4 replacement**: `_execute_tool` now does a single phase check:

```python
is_mutation_tool = tool_name in MUTATION_TOOLS and tool_name != "make_plan"
if is_mutation_tool:
    phase = v1_session.execution_state.phase
    if phase != "executing":
        return f"BLOCKED: mutation tool {tool_name!r} requires phase 'executing'; ..."
```

Authorization signal: `execution_state.phase == "executing"`.
This phase is set by `mutation_confirmation` handler via `StateMachine.confirm(session)`.

### 2. `agent_runtime.py` — `_postprocess_tool` extracted

Post-dispatch bookkeeping (tool step counter, `_current_turn_tools`, operational state update,
journal logging, session persistence) is now in its own `_postprocess_tool` method.
Called unconditionally after every successful dispatch.

### 3. `agent_runtime.py` — dead methods removed

47 methods that wrapped deleted imports from `runtime_governance`,
`runtime_execution`, `runtime_context`, and `runtime_planning` were removed:

- All `_render_plan_approval_message`, `_request_conversational_plan_response`,
  `_build_pending_plan_snapshot`, `_request_conversation_only_response`,
  `_request_plan_validation_failure_response`, `_request_denied_plan_response`
- All `_register_current_plan`, `_new_plan_id`, `_new_approval_token`,
  `_build_replan_payload`, `_get_current_stage`, `_advance_stage_after_success`,
  `_render_replan_message`, `_recover_inconsistent_state`,
  `_interpret_plan_chat_action`, `_apply_chat_plan_action`,
  `_expire_current_plan_for_goal_override`, `_check_parsimony_gate`
- All `_detect_intent`, `_classify_task`, `_assess_continuity`,
  `_inventory_context_sources`, `_decide_next_step_strategy`,
  `_is_explicit_read_request`, `_task_requires_mutation`, `_predict_context_reads`,
  `_extract_tools_from_plan_steps`, `_build_plan_preview`, `_default_plan_steps`,
  `_derive_concrete_steps_and_tools`, `_build_reasoning_summary`,
  `_infer_plan_impacts`, `_build_plan_stages`, `_suggest_stage_tools`,
  `_build_routing_policy`, `_build_plan_gate`, `_infer_plan_type`,
  `_normalize_plan_type`, `_normalize_plan_mode`, `_is_context_plan_type`,
  `_is_execution_plan_type`, `_validate_plan_preview`
- All `_select_knowledge`, `_activate_analytical_skills`, `_build_system_prompt` (legacy),
  `_build_conversation_only_response`, `_classify_prompt_route`,
  `_analyze_execute_code_fallback`, `_extract_manual_roundtrip`,
  `_request_guided_text_response`

**Kept**: `_extract_tree_name`, `_extract_node_name`, `_build_structural_index_entry`,
`_update_operational_state_from_tool`, and all `# Helpers` section methods.

Dead `__init__` fields also removed: `_plan_made_this_goal`, `_current_task_class`,
`_routing_policy`, `_plan_gate`, `_mutation_lock`, `_explicit_read_requested`,
`_last_plan_summary`, `_staged_plan`, `_current_plan_id`, `_current_approval_token`,
`_approval_granted_for_turn`, `_approval_resume_requested`, `_execution_started_logged`,
`_stage_execution_logged`.

Removed legacy imports:
- `runtime_governance.*` (approval-token helpers)
- `runtime_execution.*` (execute_tool, stage helpers)
- Most of `runtime_planning.*` (only 5 items kept: FOCAL_READ_TOOLS, MUTATION_TOOLS,
  build_structural_index_entry, extract_node_name, extract_tree_name)
- `runtime_context.*` (build_system_prompt, select_knowledge, activate_analytical_skills,
  load_knowledge_snippet kept via direct import)

File shrank from ~1 270 to ~500 lines.

### 4. `mutation_confirmation.py` handler — phase pre-transition

The handler now calls `_sm.confirm(session)` **before** any tool dispatch to transition
`execution_state.phase` from `awaiting_confirmation` → `executing`.  Without this, the
new `_execute_tool` gate would block all mutation tools.

```python
try:
    _sm.confirm(session)          # awaiting_confirmation → executing
except Exception:
    if session.execution_state.phase != "executing":
        session.execution_state.set_phase("executing")
```

### 5. `execution_prechecks.py` — tombstoned

File replaced with a module-level `__getattr__` that raises `ImportError` on any attribute
access.  Clear error message directs callers to the new phase-based approach.

### 6. `runtime_governance.py` — tombstoned

Same pattern.  All approval-token and plan-lifecycle functions removed.  Any import of the
old functions raises `ImportError`.

### 7. `tests/test_plan_approval_policy.py` — retired

13 tests that exercised `recover_inconsistent_state` and approval-token helpers were
retired (replaced with a single `skipTest` placeholder pointing to
`test_approval_phase4.py`).

### 8. `tests/test_approval_phase4.py` — new test suite

26 new tests covering:

| Group | Tests |
|---|---|
| `TestStateMachineConfirmationFlow` | idle→propose→awaiting→confirm→executing→succeeded→idle; deny path; failed→reset; invalid transition raises |
| `TestExecuteToolPhaseGate` | read tools allowed from any phase; mutation blocked when idle/awaiting; mutation allowed when executing; make_plan not gated; journal log on block; v1 session used for phase check |
| `TestTombstoneGuards` | execution_prechecks raises ImportError; runtime_governance raises ImportError |
| `TestTurnRouterPhaseGatesPhase4` | No regression: yes→confirmation, no→denial, failed→recovery, override, idle mutation, idle diagnosis |

---

## Compatibility layers still remaining

* Legacy `_session_state` flat dict still loaded in `run_turn` for tool compat.
* `_sync_v1_to_legacy` mirrors v1 session back to flat dict after each turn.
* `runtime_planning.py`, `runtime_context.py`, `runtime_state_sync.py` still present;
  only a small subset is imported in Phase 4.
* `runtime_agent_loop.py` still checks `runtime._halt_execution` (kept as field; never
  set `True` in the Phase 4 path).
* `runtime_execution.py` still present but no longer imported by `agent_runtime.py`.
  Phase 5 (Dispatcher Consolidation) will clean up remaining dispatch wiring.

---

## What remains for Phase 5+

Phase 5 should start from this state:

* Dispatcher consolidation: `execution_dispatch.py` + `runtime_agent_loop.py` use
  the new `_execute_tool`; `runtime_execution.py` can be tombstoned.
* Remove `_current_plan_id`, `_current_approval_token` instance fields (already
  removed in Phase 4).
* `runtime_planning.py` trimmed to just the 5 items currently imported.
* Knowledge retriever wiring (Phase 6).
* Failure policy (Phase 7).
* UI layering (Phase 8).
* MCP cleanup (Phase 9).
