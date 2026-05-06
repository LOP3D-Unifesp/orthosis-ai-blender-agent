# PHASE1_NOTES.md

> Phase 1 of `REFATOR_PLAN.md` — structured session schema foundation.
> Status: complete. All 116 tests in `tests/` pass.

---

## What was changed

### New subpackage: `blender_addon/session/`

Four new modules implementing the v1 structured session schema described in
REFATOR_PLAN.md §7. The legacy `blender_addon/session_store.py` was **not**
modified — it remains the live runtime's source of truth during the
coexistence window.

* `blender_addon/session/__init__.py` — public exports for the v1 schema.
* `blender_addon/session/schema.py` — dataclasses for the seven domain blocks
  (`Identity`, `Focus`, `BaselineWorkspace`, `History`, `ExecutionState`,
  `UIState`, `Lifecycle`) plus the top-level `Session`. Each block carries
  `to_dict` / `from_dict`, and `Session` enforces three invariants directly
  on the dataclass:
  * `update_focus(...)` automatically marks the baseline stale and clears
    any pending mutation when the focus signature changes.
  * `mark_baseline_stale()` clears the pending mutation as well, because a
    proposal built against a now-stale baseline cannot be trusted.
  * `set_pending_mutation(...)` always binds the mutation to the current
    focus signature and forces `phase = awaiting_confirmation`.

  The schema deliberately has **no** approval tokens, plan tokens,
  `presented_plan_*` fields, or per-stage data — the entire "Do Not Preserve"
  list (REFATOR_PLAN.md §12, items 3–10, 14–18, 21, 25–27) is excluded by
  construction.

* `blender_addon/session/store.py` — `SessionV1Store` plus the
  `migrate_legacy_state` function. Persistence rules:
  * V1 files live under `runtime/sessions_v1/` (separate from the legacy
    `runtime/sessions/` directory).
  * `load(blend_path)` checks the v1 path first, then the legacy path (in
    which case it migrates on the fly), then falls back to a fresh
    `Session.new(blend_path)`.
  * `load(...)` never mutates the legacy file. The migration is purely
    in-memory unless `save(...)` is called afterwards.
  * `save(...)` always writes to the v1 directory.

  `migrate_legacy_state(...)` is the one-shot 0.1 → 1.0 converter:
  * `session_id` → `Identity.session_id` (also recorded in
    `Lifecycle.prior_session_ids`).
  * `last_target_tree` / `session_memory.target_tree` → `Focus.tree_name`.
  * `last_gn_summary` / `last_scene_summary` → `BaselineWorkspace.structural_summary`
    (kept stale).
  * `structural_index` → `BaselineWorkspace.subgraph_index`.
  * `session_memory.last_parameter_changes` → `BaselineWorkspace.known_parameters`.
  * `session_memory.last_hypothesis` → `BaselineWorkspace.open_questions`.
  * `chat_history` → `History.messages` (invalid items dropped, bound applied).
  * `debug_mode` / `explicit_override_mode` / `mcp_write_enabled` → `UIState`.
  * `last_failure` → `ExecutionState.last_failure` (as a `LastFailure` object).
  * Everything else (every approval token, plan token, plan stage,
    `presented_plan_*`, `execution_policy`, etc.) is silently dropped.

* `blender_addon/session/baseline.py` — `BaselineBuilder` scaffolding plus the
  `compute_tree_signature` helper. Phase 1 ships:
  * `rebuild_from_summary(...)` — replaces the baseline content with a fresh
    snapshot, signs it, and clears the stale flag.
  * `mark_stale()`, `is_built()`, `is_stale()`, `matches_signature(...)`.
  * `is_sufficient_for(requires={...})` — the Phase-1 stub of the "is the
    baseline sufficient?" probe that the Phase 2 turn router will consult.

  The actual structural-summary capture still lives in legacy
  `blender_addon/capture.py`. Phase 2 will plug it in.

* `blender_addon/session/history.py` — `BoundedHistory` wrapper around
  `History`. Enforces the role allow-list (`user`/`assistant`/`system`),
  enforces `max_messages`, and accepts an optional `summariser` callback that
  Phase 2 can wire to a real LLM-driven summariser. A failing summariser
  callback never raises through the writer.

### Minimal change to `agent_runtime.py`

Two additions, both behind the feature flag and otherwise inert:

* `USE_STRUCTURED_SESSION_V1` constant. Defaults to `False` and reads
  `ORTHOSIS_USE_STRUCTURED_SESSION_V1` from the environment so the flag can
  be flipped without editing code.
* `load_structured_session_v1(project_root, blend_path)` — lazy helper that
  imports `blender_addon.session.SessionV1Store` and returns a `Session`
  object. The import is local to the function so the v1 modules pay zero
  load cost when the flag is off.

No other code path in `agent_runtime.py` consults the flag yet. The legacy
`SessionStore` is still imported and used exactly as before.

### New tests: `tests/test_session_schema_v1.py`

29 tests, all `unittest`-based to match the existing suite. Coverage:

* **Schema construction (5)** — defaults, schema version, deterministic focus
  signature, phase enum validation, lifecycle bound + dedup.
* **Session invariants (5)** — focus change clears pending mutation and marks
  baseline stale; same-coordinate focus update is a no-op; `mark_baseline_stale`
  drops the pending mutation; `clear_pending_mutation` returns to idle;
  `set_pending_mutation` binds to the current focus.
* **Bounded history (5)** — invalid roles rejected, valid messages stored
  with metadata, max-message bound enforced, summariser callback receives
  evicted messages, dict-batch `extend(...)` skips invalid items.
* **Baseline builder (4)** — rebuild marks fresh and signs, signature is
  dict-order-independent, unknown `built_from` rejected, `is_sufficient_for`
  honours requested blocks.
* **Persistence round-trip (5)** — full session round-trip preserves all seven
  blocks, fresh load returns empty session bound to blend_path, save writes
  only to `sessions_v1/` (never touches the legacy `sessions/` dir),
  serialised JSON has the right top-level keys, pending mutation round-trips.
* **Legacy migration (4)** — full 0.1 → 1.0 conversion, including a
  `_assert_no_do_not_preserve_fields` check that scans the serialised payload
  for every forbidden key; auto-migration on `load(...)` when only a legacy
  file exists; legacy file is never touched on read; v1 file takes precedence
  over legacy when both exist; saving after migration creates the v1 file
  while leaving the legacy file alone.
* **Feature flag plumbing (1)** — `SessionV1Store.load(...)` returns a
  `Session` instance with the right schema version. (The actual env-var
  toggle was smoke-tested manually because reloading `agent_runtime` requires
  the full Blender import chain to be importable.)

### What was *not* changed

* `blender_addon/session_store.py` — untouched. The legacy `SessionStore`
  is still the source of truth for `agent_runtime` and `chat_ui`.
* `runtime/sessions/` on disk — untouched. The migration path is read-only
  for legacy files.
* All other modules in `blender_addon/` — no edits.
* The 10 existing `test_session_store.py` tests still pass unchanged.

---

## Temporary compatibility layers added

* **Parallel persistence directories.** `runtime/sessions/` (legacy 0.1) and
  `runtime/sessions_v1/` (v1) coexist. Phase 2 will collapse this once the
  router stops consulting `SessionStore`.
* **Lossy migration bridge.** `migrate_legacy_state(...)` is intentionally
  one-way: it reads a legacy dict and produces a v1 `Session` while
  discarding fields the new architecture rejects. There is *no* reverse
  bridge — and per REFATOR_PLAN.md §12, there will never be one.
* **`USE_STRUCTURED_SESSION_V1` feature flag** in `agent_runtime.py`. Off by
  default. Exists so Phase 2 can flip the runtime over to the v1 schema in
  one place. Phase 1 only adds the constant + the lazy helper; the flag is
  not yet checked anywhere in the runtime.

No other temporary shims were necessary. Because the live runtime still
talks exclusively to the legacy `SessionStore`, no adapter is needed to back
the legacy code with the new schema in Phase 1. The schemas are in genuine
parallel until Phase 2 starts moving runtime call sites over.

---

## What remains for Phase 2

In dependency order, matching REFATOR_PLAN.md §11 Phase 2:

1. **Runtime convergence.** Create `runtime/core.py` (`Runtime`) and move
   `AgentRuntime` responsibilities into it. Reroute the in-Blender socket
   server (`blender_addon/server.py::RuntimeBridgeCore`) to call the central
   `Runtime` instead of running parallel cognition. Delete `RuntimeBridgeCore`,
   the literal `"chatgpt"` leftover at `server.py:192`, and the double
   `bump_turn_counter` call.
2. **Flip the feature flag.** Once the central `Runtime` exists, change
   `USE_STRUCTURED_SESSION_V1` to default `True`, have the runtime load
   sessions through `SessionV1Store`, and start consuming `Session` directly
   instead of the legacy flat dict.
3. **Retire the legacy session store.** When no remaining call site reads
   the flat dict, delete `blender_addon/session_store.py` and the legacy
   `runtime/sessions/` directory (after a one-shot disk migration of any
   files the user still has).
4. **Wire the real structural summary into `BaselineBuilder`.** Phase 1
   provides the data shape only; Phase 2 should call into `capture.py`
   (which will move under `transport/` later) so `rebuild_from_summary`
   reflects the live tree.
5. **Wire the summariser callback** in `BoundedHistory` to the eventual
   small-LLM summariser. Phase 1 leaves this as a no-op hook.
6. **Begin the turn router and handlers** (REFATOR_PLAN.md §8). The
   `Session.execution_state.phase` enum and the `set_pending_mutation` /
   `clear_pending_mutation` invariants are already in place to back the
   state machine.

Nothing in the Phase 2–9 list is started here. Phase 1 only delivers the
session foundation that the rest of the refactor will build on.
