# PHASE5_NOTES.md

> Phase 5 of `REFATOR_PLAN.md` — Dispatcher Consolidation (Workstream G).
> Status: complete for Phase 5 scope. The system remains runnable.
> Verification: `python -m unittest discover -s tests` → 190 tests (187 pass, 2 skip, 1 pre-existing MCP error).

---

## What changed

### 1. New `blender_addon/execution/` subpackage

**`execution/__init__.py`** — public API:
```python
from .execution import dispatch_tool, process_screenshot_result
# backward-compat alias:
dispatch_runtime_tool = dispatch_tool
```

**`execution/dispatcher.py`** — canonical dispatch implementation:
- Absorbs `execution_dispatch.py`
- `dispatch_tool(runtime, tool_name, tool_input) → (raw_dict, result_str, elapsed_ms)`
- Reads session-state flags (`debug_mode`, `explicit_override_mode`, `mcp_write_enabled`, `blend_path`) from `runtime._session_state`
- Delegates to `tools.dispatch_tool_raw` for socket communication
- `process_screenshot_result` handles `capture_screenshot` → `send_screenshot_turn` path

This is now the **real dispatch path**. `agent_runtime._execute_tool` imports `dispatch_tool` from here.

### 2. `agent_runtime.py` — import update

```python
# Before (Phase 4):
from .execution_dispatch import dispatch_runtime_tool, process_screenshot_result

# After (Phase 5):
from .execution import dispatch_tool, process_screenshot_result
```

`_execute_tool` now calls `dispatch_tool(self, tool_name, tool_input)` directly.

### 3. `execution_dispatch.py` — redirect shim

No longer contains logic.  Re-exports from `execution.dispatcher` so any direct importers
(tests, third-party scripts) continue to work without changes:

```python
from .execution.dispatcher import dispatch_tool as dispatch_runtime_tool
from .execution.dispatcher import dispatch_tool, process_screenshot_result
```

### 4. `runtime_execution.py` — tombstoned

Already had no live importers since Phase 4. Replaced with module-level `__getattr__`
that raises `ImportError` with a clear redirect message.

### 5. `execution_postprocess.py` — tombstoned

Was only imported by `runtime_execution.py` (also tombstoned). Replaced with the same
`__getattr__` pattern.

### 6. `runtime_planning.py` — simplified from 1 574 → 191 lines

Removed 1 393 lines of dead pipeline functions. These functions were exclusively called
from `agent_runtime.py` methods deleted in Phase 4, or from tombstoned modules
(`runtime_execution.py`, `execution_postprocess.py`, `runtime_governance.py`).

**Dead functions removed:**
`_dedupe`, `_has_useful_session_memory`, `_conversation_has_specific_target`,
`_looks_like_constructive_request`, `_extract_tree_name_hint`, `_semantic_tokens`,
`_recent_user_history_goal`, `_filter_tools_for_plan_type`, `infer_context_plan_mode`,
`build_question_only_steps`, `build_collaboration_options`, `build_conversational_opening`,
`build_conversation_only_response`, `classify_prompt_route`, `detect_intent`,
`assess_continuity`, `inventory_context_sources`, `decide_next_step_strategy`,
`classify_task`, `is_explicit_read_request`, `task_requires_mutation`,
`predict_context_reads`, `extract_tools_from_plan_steps`, `default_plan_steps`,
`derive_concrete_steps_and_tools`, `build_reasoning_summary`, `infer_plan_impacts`,
`suggest_stage_tools`, `build_plan_stages`, `build_routing_policy`, `build_plan_gate`,
`infer_plan_type`, `validate_plan_preview`, `build_plan_preview`

**Live exports kept:**
- Constants: `MUTATION_TOOLS`, `FOCAL_READ_TOOLS`, `BROAD_READ_TOOLS`,
  `CONTEXT_DISCOVERY_TOOLS`, `PLAN_TYPE_*`, `PLAN_MODE_*`, regex patterns
- Functions: `normalize_plan_type`, `normalize_plan_mode`, `is_context_plan`,
  `is_execution_plan`, `is_question_only_context_plan`, `is_tool_context_plan`,
  `extract_tree_name`, `extract_node_name`, `build_structural_index_entry`

### 7. `tests/test_approval_phase4.py` — patch path updated

`_patch_dispatch` patch target changed from `blender_addon.agent_runtime.dispatch_runtime_tool`
to `blender_addon.agent_runtime.dispatch_tool` to match the Phase 5 rename.

### 8. `tests/test_execution_phase5.py` — new test suite

38 new tests covering:

| Group | Tests |
|---|---|
| `TestExecutionSubpackageAPI` | dispatch_tool importable; process_screenshot importable; backward-compat alias exists and is same object; execution_dispatch shim re-exports correctly |
| `TestDispatchTool` | returns 3-tuple; raw is dict; result is str; elapsed_ms is non-neg int; session flags forwarded; route=product; user_confirmed=True; format_result called; empty session_state uses defaults |
| `TestProcessScreenshotResult` | non-screenshot → ''; execute_code → ''; capture_screenshot calls send_screenshot_turn; logs visual_evidence_processed |
| `TestTombstoneGuardsPhase5` | runtime_execution raises ImportError; execution_postprocess raises ImportError |
| `TestRuntimePlanningSimplified` | importable; < 250 lines; live exports present; dead functions gone; build_structural_index_entry works |

---

## Execution/dispatch legacy surfaces that remain

| Module | Status | Notes |
|---|---|---|
| `execution/dispatcher.py` | **Live — canonical** | Phase 5 dispatch surface |
| `execution/__init__.py` | **Live** | Public re-export |
| `execution_dispatch.py` | Live shim | Re-exports from `execution`; keep until Phase 6+ cleanup |
| `tools.py` | **Live — untouched** | Socket-level tool calls to Blender; Phase 5 did not touch |
| `runtime_dispatch.py` | **Live — server side** | Runs inside Blender; `RuntimeDispatcher` class used by `server.py`. Phase 5 did not touch (requires Blender runtime) |
| `safety_policy.py` | **Live — server side** | Imported by `runtime/core.py` → `execute_tool_call()` → `server.py`. Phase 5 did not touch |
| `skill_router.py` | **Live — server side** | Imported by `runtime_dispatch.py` inside Blender. Phase 5 did not touch |
| `runtime_execution.py` | Tombstoned | No live importers since Phase 4 |
| `execution_postprocess.py` | Tombstoned | No live importers since Phase 4 |
| `execution_prechecks.py` | Tombstoned (Phase 4) | Gate cascade removed |
| `runtime_governance.py` | Tombstoned (Phase 4) | Approval tokens removed |

---

## What is deferred to Phase 6+

### Phase 6 — Knowledge Retrieval
- Introduce `knowledge/retriever.py` to replace ad-hoc knowledge snippet loading.
- `TurnContext` handlers currently load knowledge from `knowledge_dir` directly.
- Phase 6 should wrap this with a typed retriever.

### Remaining server-side cleanup (Phase 5+ or separate pass)
The following are **still alive on the Blender server side** and were not touched:
- `runtime_dispatch.py` (1 100+ lines) — `RuntimeDispatcher` class  
- `safety_policy.py` — `SafetyContext`, `evaluate_tool_call`
- `skill_router.py` — analytical skill routing

These run inside Blender and cannot be tested without a live Blender process.
Per REFATOR_PLAN.md Phase 5, merging them into `execution/handlers.py` is the correct
next step but requires careful integration testing in a Blender environment.
Deferred to avoid breaking the Blender server without a way to verify.

### Dead context modules (not yet tombstoned)
`runtime_context.py`, `context_prompt.py`, `context_knowledge.py`, `context_skills.py`
are no longer imported by any live code path (agent_runtime.py removed all references
in Phase 4). They can be tombstoned in a future cleanup pass.

### `execution_dispatch.py` shim
Can be tombstoned (removed) once there are no external callers using the old name.
