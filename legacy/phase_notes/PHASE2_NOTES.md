# PHASE2_NOTES.md

> Phase 2 of `REFATOR_PLAN.md` — runtime convergence foundation.
> Status: complete for Phase 2 scope only. The system remains runnable.
> Verification: `python -m unittest discover -s tests` -> 121 tests passed.

---

## What changed

### 1. `Runtime` is now the live in-Blender bridge runtime

The in-Blender socket bridge no longer ships its own separate runtime
implementation.

* `blender_addon/server.py`
  * now imports and instantiates `blender_addon.runtime.Runtime` directly;
  * keeps `RuntimeBridgeCore = Runtime` as a temporary compatibility alias for
    tests and any callers still importing the old name during the convergence
    window;
  * preserves the existing socket protocol and low-level direct handlers.

This completes the Phase 2 reroute away from the duplicated socket-path
runtime without starting the Phase 3 turn-router rewrite.

### 2. `runtime/core.py` is now an actual runtime foundation, not just a stub

`blender_addon/runtime/core.py` now does more than mirror the old
`RuntimeBridgeCore` methods:

* wraps the legacy `SessionStore` in a `SyncedSessionStore` bridge;
* mirrors legacy saves into `SessionV1Store` automatically;
* maps legacy runtime/session data into the v1 structured session as a
  best-effort Phase 2 compatibility layer:
  * focus tree,
  * UI flags,
  * chat history,
  * last failure,
  * pending execution-plan confirmation,
  * baseline workspace hints;
* applies tool-aware structured-session updates:
  * structural read tools (`get_tree_structure`, `analyze_gn_state`) rebuild
    the v1 baseline,
  * mutation tools mark the v1 baseline stale,
  * `get_changes_since_last_turn` marks the baseline stale when changes exist.

The legacy flat dict is still authoritative. Phase 2 only establishes the
parallel v1 runtime state so Phase 3 has real persisted data to build on.

### 3. `AgentRuntime` can now sit on top of the shared `Runtime`

`blender_addon/agent_runtime.py` now accepts an optional `runtime` argument.
When used, it reuses the shared:

* `session_store`
* `journal`
* `dispatcher`

This starts runtime convergence without changing the legacy chat turn logic in
`runtime_turn.py`.

Important: the chat pipeline itself is still the old pipeline. This change is
foundational only.

### 4. Phase 2 bug fixes are live in the real server path

* The `"conversation_surface_primary": "chatgpt"` leftover is gone from the
  runtime session state returned by the live bridge path.
* The extra `bump_turn_counter()` in socket/UI mode changes is gone. Turn
  counting remains in the chat-turn path only, so UI control commands no
  longer inflate the counter.

### 5. Tests added/updated

New test file:

* `tests/test_runtime_convergence_phase2.py`

Coverage added:

* `RuntimeBridgeCore` compatibility alias now points at `Runtime`
* session state no longer exposes the `"chatgpt"` leftover
* `set_modes()` does not bump `turn_counter`
* legacy saves mirror into Session v1
* `AgentRuntime` can share the central `Runtime` foundation

Existing relevant suites still pass:

* plan approval policy
* Session v1 schema/store tests
* MCP server surface tests

---

## Compatibility layers still remaining

These are intentional Phase 2 holdovers and were **not** removed yet:

* `RuntimeBridgeCore = Runtime` alias in `blender_addon/server.py`
  * kept only as a compatibility shim during convergence
* legacy `SessionStore` and `runtime/sessions/`
  * still the live source of truth
* `SessionV1Store` and `runtime/sessions_v1/`
  * secondary mirrored persistence only
* `AgentRuntime` + `runtime_turn.run_turn`
  * still the live chat turn pipeline
* plan-token / approval-token legacy flow
  * still present in the chat/runtime-turn path
* root MCP adapter (`server.py` at repo root)
  * still works through the bridge and remains secondary

Phase 2 deliberately does **not** remove these yet.

---

## What remains for Phase 3

Phase 3 should start from this state:

* move chat turns onto the central runtime instead of the legacy
  `AgentRuntime`/`runtime_turn` orchestration path;
* introduce the router / handlers / state-machine work;
* stop treating approval tokens and legacy plan fields as live runtime truth;
* promote Session v1 from mirrored persistence to the actual runtime session
  model;
* remove the temporary `RuntimeBridgeCore` alias once nothing imports it;
* retire direct legacy-session plumbing that only exists to bridge Phase 2.

Out of scope for this phase and intentionally not started:

* full turn-router / handler refactor
* full replacement of the legacy `SessionStore` flow
* broad MCP redesign
* speculative architecture cleanup beyond runtime/session convergence

---

## Discrepancy Between Claude's Partial Summary And The Actual Repo State

The codebase did **not** fully match the partial summary when inspected.

### Confirmed discrepancies

* `blender_addon/runtime/__init__.py` and `blender_addon/runtime/core.py`
  had been created, as reported.
* But `blender_addon/server.py` was still carrying the full old
  `RuntimeBridgeCore` implementation.
  * So the server path had **not** actually been rerouted yet.
* `blender_addon/runtime/core.py` already claimed `RuntimeBridgeCore` was
  deleted, but that was not true in the live code.
* `blender_addon/runtime/core.py` also claimed `AgentRuntime` already accepted
  an optional shared `Runtime`, but the actual `AgentRuntime` constructor did
  not yet have that parameter.
* Session v1 existed from Phase 1, but it was **not** being kept in sync with
  live runtime saves. Only the helper/test path could load it.
* The `"chatgpt"` leftover and the extra `bump_turn_counter()` call were still
  present in the real `blender_addon/server.py` implementation.
* The workspace does not currently contain a `.git` directory, so repository
  state inspection had to be treated as filesystem state plus test status
  rather than Git branch/diff state.

### How Phase 2 resolved those discrepancies

* rerouted the live bridge to `Runtime`;
* kept a compatibility alias instead of leaving two real implementations;
* added the missing `AgentRuntime(runtime=...)` convergence hook;
* added live Session v1 mirroring;
* removed the live `"chatgpt"` response field;
* removed the live extra turn-counter bump.

---

## Notes

`USE_STRUCTURED_SESSION_V1` still defaults to off in `agent_runtime.py`.
That is intentional in this Phase 2 implementation because the chat turn loop
still uses the legacy flat dict directly. The structured session is now
mirrored in parallel instead of silently idle, which is enough for Phase 2
without prematurely starting Phase 3.
