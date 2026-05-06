# PHASE8_NOTES.md — UI Layering

> Phase 8 of REFATOR_PLAN.md — Workstream H
> Implemented: 2026-04-07

---

## What Phase 8 is

Workstream H: UI Layering. The chat panel speaks first in plain prose.
Advanced/debug controls live in a collapsed sub-panel. No plan dumps, no
approval tokens, no runtime metadata on the default surface.

---

## What changed

### 1. `blender_addon/chat_ui.py` — split and replaced with a thin shim

The original 2116-line monolith was split into a `ui/` package (5 files).
`chat_ui.py` now contains only backward-compatibility exports:

```python
from .ui.chat_session import SESSION
def register(): from .ui import register as _r; _r()
def unregister(): from .ui import unregister as _u; _u()
```

`blender_addon/__init__.py` still calls `chat_ui.register()` — unchanged.

### 2. `blender_addon/ui/` — new package

| File | Contents |
|---|---|
| `__init__.py` | Lazy `register`/`unregister` + `SESSION` re-export |
| `chat_session.py` | `_ChatSession` class + `SESSION` singleton — **no bpy import** |
| `_helpers.py` | `_wrap_text`, `_normalize_multiline_text`, `_PHASE_LABELS`, `_get_execution_phase` — **no bpy import** |
| `screenshot.py` | `_run_screenshot_capture()` + `CHAT_OT_AttachScreenshot` |
| `advanced.py` | `CHAT_PT_RuntimeDebug` + `CHAT_OT_ApplyModes` — `DEFAULT_CLOSED` sub-panel |
| `panel.py` | `CHAT_PT_Panel` + all main operators + `OrthosisAddonPreferences` + `register()`/`unregister()` |

The `ui/__init__.py` is lazy: importing `blender_addon.ui` does **not** pull
`bpy` into the process. Only `SESSION` is eagerly available. `register()` and
`unregister()` load `panel.py` (and thus `bpy`) only when called inside Blender.
This makes `chat_session.py` and `_helpers.py` fully testable in CI.

### 3. Dead operators removed (9 operators gone)

All nine referenced the pre-Phase-4 approval-token / plan-token / control-owner
system which was completely deleted in Phases 3–5.

| Removed | Reason |
|---|---|
| `CHAT_OT_ApprovePlan` | Approval tokens deleted in Phase 4 |
| `CHAT_OT_DenyPlan` | Same |
| `CHAT_OT_ResetPendingPlan` | Old plan semantics gone |
| `CHAT_OT_ClearApprovalState` | Approval tokens gone |
| `CHAT_OT_ResetTransientState` | Control-owner system gone |
| `CHAT_OT_RebuildPlan` | Plan rebuilding gone |
| `CHAT_OT_TakeControl` | Control-owner system gone |
| `CHAT_OT_ContinueSession` | Socket-only, duplicated by StartSession |
| `CHAT_OT_ApplyModes` (main panel) | Moved to `advanced.py` |

### 4. `_get_runtime_ui_state()` — dead fields removed

Approximately 30 flat-dict keys that are never set in the Phase 3+ runtime
were removed from the snapshot:

**Gone:** `approval_token`, `approval_status`, `approval_required`,
`approval_pending`, `current_plan_id`, `current_plan_status`, `plan_pending`,
`presented_plan_*`, `fallback_plan_id`, `fallback_approval_token`,
`execution_plan_id`, `execution_approval_token`, `control_owner`,
`control_owner_locked`, `superseded_plan_id`, `last_replan`, `session_memory`,
`local_scope`, `structural_index`, `next_action_expected`, `resumed_session_state`,
`session_resumed`, `state_inconsistencies`.

**Added:** `execution_phase` — read from the V1 structured session
(`execution_state.phase`) so the panel can show a phase badge when non-idle.

### 5. Main panel — prose-first surface

`CHAT_PT_Panel`:

- Panel label: `"Claude Chat (Legacy)"` → `"GN Copilot"` (accurate name).
- "Runtime Overview" box removed. Replaced with a compact single row: `New Session | End | Journal`.
- Phase badge: when `execution_state.phase` is non-idle (awaiting_confirmation, executing, failed, halted, etc.), a one-line badge appears above the chat history.
- Chat history rendering: first line of each assistant message is slightly taller (`scale_y = 0.85`) for readability; subsequent lines at `scale_y = 0.72`. Role labels: "You" / "Agent" (was "AI:").
- Removed Portuguese text ("Aprovação e replanejamento acontecem por conversa no chat.").
- Attachment indicators: condensed to single-line format.
- Input/send area: unchanged.

### 6. Advanced panel — cleaned up

`CHAT_PT_RuntimeDebug`:

- Removed buttons for dead operators (ApprovePlan, DenyPlan, RebuildPlan,
  TakeControl, ResetPendingPlan, ClearApprovalState, ResetTransientState).
- Removed display of dead fields (Plan ID, Plan Status, Approval Token,
  Approval required/status, Control Owner).
- Added `execution_phase` from V1 structured session.
- Surviving controls: Debug/Override/MCP-Write flags + Apply Flags, Clear Chat UI,
  session info, model, task class, target tree, last turn tools.
- Moved here: `CHAT_OT_ApplyModes` (was in `_MAIN_CLASSES`, now in `advanced.py`).

### 7. `_ChatSession.clear()` — bug fix

`self.running` was not being reset in `clear()`. Fixed. The old `chat_ui.py`
had `SESSION.running = False` (line ~96); the split had accidentally omitted it.

### 8. `tests/test_context_knowledge.py` — cleanup

This test file was failing at collection time because it tried to import
`context_knowledge.select_knowledge` — a symbol tombstoned in Phase 6 that
raises `ImportError` by design. The module-level import caused the file to fail
with an ERROR on every test run, polluting the output.

Replaced with a single test that explicitly verifies the tombstone behavior.

---

## Tests

### Updated tests

- `tests/test_context_knowledge.py` — rewritten as a tombstone verification test.

### New test file

`tests/test_ui_phase8.py` — 37 tests across 7 classes:

| Class | What it tests |
|---|---|
| `TestChatSession` | `_ChatSession` fully exercised without bpy: add, clear, replace_messages, reset_turn, screenshot/file queues, thread safety |
| `TestSessionSingleton` | `SESSION` importable from `ui.chat_session`, `ui`, and `chat_ui` shim |
| `TestDeadOperatorsRemoved` | Source inspection confirms 8 dead operator `bl_idname`s absent from `panel.py` |
| `TestWrapText` | `_wrap_text` handles empty, short, long, multi-paragraph text |
| `TestPhaseBadge` | `_PHASE_LABELS` covers all non-idle phases; no "idle" entry |
| `TestGetExecutionPhase` | `_get_execution_phase` returns `""` (no exception) when session unavailable |
| `TestUiPackageStructure` | Package importable, shim exports `register`/`unregister` |

### Test results after Phase 8

```
Ran 295 tests in ~0.3s
OK (skipped=2)
```

- **0 errors** — the pre-existing `test_context_knowledge` error is now gone.
- **2 pre-existing skips** — unchanged.
- **All 37 Phase 8 tests** — PASS.

---

## Old UI surfaces that remain

| Surface | Status |
|---|---|
| `blender_addon/chat_ui.py` | Shim only — kept for `__init__.py` backward compat |
| Socket-based session calls (`_runtime_set_modes`) | Still present in `panel.py` — used by `CHAT_OT_ApplyModes` in the Advanced panel for debug flags |
| `_start_local_runtime_session` / `_end_local_runtime_session` | Still call legacy `SessionStore` flat-dict API — Phase 9 will replace with V1 session path |
| Legacy `_get_runtime_ui_state` reading from flat-dict session | Cleaned up but still uses `SessionStore.load()` — Phase 9 will flip to V1 only |

---

## What is deferred to Phase 9

1. **MCP decision**: `mcp/` adapter vs removal. `server.py` still exists as a thin wrapper. Phase 9 decides to keep thin or delete.

2. **Final chat path on V1 session**: `_start_local_runtime_session` still uses the legacy `SessionStore` flat-dict API. Phase 9 completes the migration so the chat path reads/writes only the V1 structured session.

3. **`chat_ui.py` shim removal**: once `__init__.py` is updated to import directly from `ui/`, the shim can be deleted.

4. **Remaining cleanup**: dead imports in `agent_runtime.py`, `runtime_state_sync.py` references in `panel.py`, any remaining Portuguese strings in knowledge corpus.

5. **Inline expandability per message**: Blender panels don't support per-message expand/collapse natively. Phase 9 could add a simple "last response" popover or text editor fallback for long responses.

---

## Invariants now enforced

1. `blender_addon.ui.chat_session` and `blender_addon.ui._helpers` are importable without `bpy` — unit-testable in CI.
2. `blender_addon.ui` package import does NOT load `bpy` — SESSION is always safe to access.
3. No approval tokens, plan IDs, or fallback tokens appear in `_get_runtime_ui_state()` or the main panel draw.
4. No dead approval-token operators in `_ALL_CLASSES` (verified by source inspection in tests).
5. Phase badge surfaces `execution_state.phase` from the V1 structured session when available.
6. `_ChatSession.clear()` correctly resets `running` to `False`.
