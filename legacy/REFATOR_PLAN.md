# REFATOR_PLAN.md

> Refactor plan for `blend_IA_ort` derived from the 14 binding architectural decisions.
> No code, no patches. Concrete, opinionated, implementation-guiding.
> Canonical language: English. Date of plan: 2026-04-06.

---

## 1. Executive Summary

The current codebase is structurally a workflow engine wearing a copilot costume. Every meaningful turn is funneled through a 12-stage pipeline (`runtime_turn.run_turn`) that classifies intent, infers a task class, builds a context plan, gates execution behind approval tokens, normalizes stages, and re-plans on failure — even when the user just asked a question. Two parallel runtimes (`AgentRuntime` in the chat UI path, `RuntimeBridgeCore` in the MCP/server path) duplicate cognition. Session state is a flat 50-key dict whose semantics are scattered across a dozen modules. Approval is keyword-driven and brittle. Knowledge is selected by regex matching. Documentation contradicts code in at least four load-bearing places.

The 14 decisions reframe the product as a **Blender-centered contextual GN copilot**, not a workflow engine. This refactor makes the code match that reframing.

The core moves are:

1. **Collapse the 12-stage pipeline into a turn router with ~9 turn handlers.** Most turns (questions, diagnosis, baseline reads) bypass planning entirely. Mutations remain explicit but lose the per-stage approval ceremony.
2. **Converge the two runtimes.** One central `Runtime`. Chat UI and MCP both adapt to it. MCP becomes a thin optional adapter.
3. **Replace the flat session dict with a structured schema** of seven domain blocks: `identity`, `focus`, `baseline_workspace`, `history`, `execution_state`, `ui_state`, `lifecycle`. Persisted across restarts. Versioned.
4. **Replace token-based approval with a state machine.** `execution_state.phase` is the only source of truth. "yes/sim" only counts in `awaiting_confirmation`. Tokens disappear from the user surface.
5. **Replace `make_plan` as a universal gate with `make_plan` as a tool used only when a mutation is non-trivial.** Reads, diagnosis, and conversation never plan.
6. **Replace recursive replan loops with a single explain-and-stop policy** after one failed mutation.
7. **Rebuild knowledge selection** around baseline structural similarity, focus, and intent signals — not keyword matching. Recipes become the central reference patterns.
8. **Layer the UI**: first what the agent understood + the proposal, then expandable detail. No second API call to "conversationalize" anything.
9. **Cut large dead surfaces**: `snapshots/`, `reference/`, `blender_mcp_package/`, several legacy docs, `skill_router.py`, the analytical "skills/" infrastructure unless it earns its keep.
10. **Standardize on English** across code, prompts, knowledge, journal, and gate messages. CLAUDE.md becomes a short operational entrypoint, not a stale architecture map.

The result is fewer files, fewer abstractions, fewer turn-paths, and a cognitive loop that feels like a technical partner instead of a state-machine compliance officer. The end-state is roughly 40-50% fewer lines of runtime code, one runtime instead of two, one session schema instead of a flat bag, one approval source of truth, and a UI that opens with a sentence instead of a 30-line plan dump.

---

## 2. Target Architecture

### 2.1 One Runtime, One Session, One Loop

A single `Runtime` object owns:

- the active **Session** (structured schema, persisted per `.blend`)
- the active **TurnRouter** (classifies and dispatches incoming user input)
- the **ExecutionStateMachine** (the only source of truth for "are we waiting on the user?")
- the **KnowledgeRetriever** (resolves focus + baseline → minimal relevant context)
- the **Dispatcher** (single tool execution surface — merges current `runtime_dispatch.py` and `execution_dispatch.py`)
- the **Journal** (append-only audit, unchanged in shape, English-only)

The chat UI path and the MCP path both call into the same `Runtime`. Neither owns its own cognition. `RuntimeBridgeCore` is deleted as a parallel implementation; its server-side responsibilities (socket handling, scene capture) move to a thin transport layer that wraps the central runtime.

### 2.2 Turn Classes (Decision 2)

Every incoming user message maps to exactly one of nine turn classes. Classification is cheap (keyword + state inspection, no LLM call). The router dispatches to a dedicated handler:

| Turn class | Triggers | Handler does |
|---|---|---|
| `greeting_or_smalltalk` | Greetings, thanks | One-line reply, no API call when trivially detectable |
| `clarification` | User asks "what does X mean", asks about session/baseline | Conversational answer, may update baseline. No plan. |
| `diagnosis` | "What's in the tree", "show me node X", "what changed" | Read tools only. No plan. No approval. |
| `baseline_refresh` | Auto-triggered when focus changes or staleness detected, or user asks "rebuild baseline" | Read-heavy, updates `baseline_workspace`. No plan. |
| `proposal` | User asks "how would you fix X", "what's the smallest change to Y" | Reads + reasoned proposal. No mutation. No plan artifact unless multi-step. |
| `mutation_request` | User asks for a change ("set scale to 1.0", "wire A to B") | Compute change, present preview, transition to `awaiting_confirmation`. Optionally `make_plan` if non-trivial. |
| `mutation_confirmation` | State is `awaiting_confirmation` AND user input matches an affirmative pattern in that state only | Execute. Single attempt. |
| `mutation_denial` | State is `awaiting_confirmation` AND user input is negative or revisionary | Drop pending mutation, return to collaborative loop. |
| `post_failure_recovery` | Last execution failed | Conversational explain-only. No replan loop. User may issue a new request. |

The first major question the runtime asks itself on every non-trivial turn is **"Is the current baseline for the focused GN modifier sufficient to answer this?"** If yes, proceed. If no, the turn becomes (or pre-emptively triggers) a `baseline_refresh` and then resumes.

### 2.3 Session Schema (Decision 12)

Session is a structured object with seven stable domain blocks. See §7 for the full proposal. Key principles:

- `focus` = the GN modifier currently in scope, not just the `.blend` file.
- `baseline_workspace` is the persistent technical understanding: tree signature, semantic layers, subgraph index, recipe associations, open questions. It survives Blender restarts and evolves during the session.
- `execution_state.phase` is a small enum (`idle | reading | proposing | awaiting_confirmation | executing | failed | halted`). The state machine is the only thing that decides whether "yes" is meaningful.
- `chat_history` is bounded and lives inside the schema, not as a sidecar concept.
- `lifecycle` tracks creation, last_active, schema_version, and continuity hints across restarts.

### 2.4 Approval State Machine (Decisions 4, 7)

Reads never require approval. Mutations always do, but approval is **state-dependent, not keyword-dependent**.

- The runtime can only enter the "actually executing a mutation" branch if `execution_state.phase == awaiting_confirmation` and the latest user message is interpreted by the `mutation_confirmation` handler.
- "yes / sim / vai / ok / bora" outside of `awaiting_confirmation` are routed to other handlers (greeting, clarification, diagnosis) — they never accidentally execute anything.
- There are no user-visible approval tokens. Tokens, UUIDs, plan ids, and approval ids are removed from the chat surface entirely. Internally, the state machine can use an opaque pending-mutation reference, but that is implementation detail.
- A pending mutation that is not confirmed within the session expires when focus changes, when the baseline is refreshed, or when the user issues a new request that classifies as something else.

### 2.5 Failure Policy (Decision 8)

After **one** failed `execute_code` (or any mutation tool):

1. The runtime stops.
2. It explains: what was tried, what failed, the likely cause, and a suggested alternative.
3. It returns to the collaborative loop in `phase = idle`.

There is no automatic replan, no fallback approval token, no recursive retry. The user decides what to do next. `REPLAN_AFTER_FAILURE`, `CODE_FALLBACK_REQUIRES_NEW_APPROVAL`, and the entire `build_replan_payload` mechanism are deleted.

### 2.6 Knowledge Architecture (Decision 10)

Knowledge selection is driven by:

- the current `focus` (what GN modifier the user is in)
- the current `baseline_workspace` (what we know about the tree shape)
- structural similarity to known recipes
- intent signals from the turn router (proposal vs diagnosis vs mutation)
- learned patterns (`learned_patterns.md` continues to exist)

It is **not** driven by regex keyword matching against the user message. The retriever returns a small ranked set with budgeted token cost. Recipes become the central reference: each recipe is a named, English, focus-tagged document with explicit "applies when" structural conditions.

The mixed Portuguese/English corpus is collapsed into one English-only canonical corpus. Files in `knowledge/domain/` and `knowledge/recipes/` are translated and consolidated. `blender_mcp_package/` knowledge is deleted as duplicate.

### 2.7 UI Layering (Decision 9)

The chat panel speaks first in plain prose:

- one-sentence summary of what the runtime understood
- one-paragraph proposal or answer
- *expandable* detail — node lists, tree diffs, plan steps, journal references — only when the user asks or clicks "show details"

The panel **never** dumps a 20-line plan as the primary message. There is **no extra API call** to "conversationalize" anything; the model is instructed to produce that layering in its primary response. The current `_render_plan_approval_message` and `_request_conversational_plan_response` are deleted.

Technical controls (debug mode, override mode, mcp_write_enabled, journal viewer, baseline inspector) move under an `Advanced` collapsible. The default surface is conversation + screenshot button + send.

### 2.8 MCP as Optional Adapter (Decision 1, 11)

MCP no longer has a parallel runtime. The root `server.py` and `blender_connection.py` are restructured as a thin FastMCP adapter that calls into the central `Runtime`. If, after this refactor, MCP turns out to add no value beyond what the in-Blender runtime already provides, it is marked for removal in a follow-up. It has no separate cognition, no separate session, no separate knowledge selection, no separate approval logic.

### 2.9 Token Budget (Decision 13)

Per turn the runtime sends:

- a stable, compact system prompt (~1-1.5K tokens)
- the persistent `baseline_workspace` summary (~0.5-1K tokens, deduplicated, only fields relevant to the current focus)
- a small recent history slice (last 6-10 messages, summarized older)
- a minimal context bundle from the `KnowledgeRetriever` (~0.5-1.5K tokens)
- the user's message

It does **not** send: 4×1400-character knowledge dumps, 4×1200-character analytical dumps, full task/context/runtime/working_memory snapshots, full presented_plan_* fields. The context budget per turn drops by an estimated 60-75%.

---

## 3. Current-to-Target Gap Map

| Area | Current state | Target state | Gap |
|---|---|---|---|
| Runtime count | Two parallel: `AgentRuntime` (chat) and `RuntimeBridgeCore` (server/MCP) | One central `Runtime` | Delete parallel implementation; thin both adapters |
| Turn pipeline | 12-stage `run_turn` pipeline runs on every non-trivial turn | 9 turn classes, 9 dedicated handlers, classifier-first dispatch | Replace `run_turn` with `TurnRouter`; delete most stage abstractions |
| Planning | `make_plan` is a mandatory first tool (`ALWAYS_PLAN_FIRST = True`); context plans + execution plans + fallback plans | `make_plan` is an optional tool used only for non-trivial multi-step mutations | Delete `ALWAYS_PLAN_FIRST`, plan-type inference, plan stages, context-plan-as-artifact |
| Approval | Token-based (`appr-{uuid}`), keyword-detected, per-stage, surfaced in chat | State-machine-based, only valid in `awaiting_confirmation`, never surfaced | Delete approval tokens, fallback approval, stage approval; introduce `phase` enum |
| Failure handling | Recursive replan loop with `build_replan_payload`, fallback plan, fallback approval | Single explain-and-stop, return to collaborative loop | Delete replan/fallback infrastructure entirely |
| Session state | Flat dict with 50+ keys spread across modules; mutated everywhere | Structured schema with 7 domain blocks, single ownership | Replace `_default_state`, refactor every reader/writer |
| Approval keywords | `_EXECUTION_RESUME_KEYWORDS` matches "ok"/"sim"/"vai"/"bora"/"yes" anywhere | Affirmative interpretation only inside `mutation_confirmation` handler | Delete the keyword regex; move logic into the state machine |
| Knowledge selection | Regex keyword matching against user message | Focus + baseline + structural similarity + intent | Replace `context_knowledge` retrieval logic |
| Knowledge corpus | Mixed PT/EN, duplicated across `knowledge/` and `blender_mcp_package/` | One English canonical corpus | Translate, consolidate, delete duplicates |
| UI rendering | 20-30 line plan dump as primary message; second API call to wrap it | First sentence is conversational; details expand on demand; one API call | Delete plan-dump renderer and conversationalization call |
| System prompt | Massive (~6-8K tokens) with task/context/runtime/working_memory/4×knowledge/4×analytical | Compact (~3-4K tokens) with baseline + small recent + retrieved minimum | Rebuild `context_prompt.build_system_prompt` |
| MCP | `server.py` (root) calls `RuntimeBridgeCore`, parallel cognition path | Thin adapter calling central `Runtime` | Rewrite root `server.py`; delete parallel logic |
| Safety policy | `safety_policy.py` exists despite CLAUDE.md saying not to | Policy collapses into the state machine + dispatcher; file deleted | Delete `safety_policy.py`, fold meaningful checks into dispatcher |
| Skill router | `skill_router.py` exists despite CLAUDE.md saying not to | Deleted | Delete |
| Snapshots | `snapshots/` contains full codebase copies | Not in repo | Delete and add to `.gitignore` |
| Reference | `reference/` contains old project Python | Deleted from repo | Delete |
| `blender_mcp_package/` | Duplicate knowledge, unclear status | Deleted | Delete |
| `contracts/` | JSON schemas not validated anywhere | Deleted unless validated; if validated, wired into dispatcher | Decide and act |
| Skills infra | `skills/gn_scene_state_interpreter/`, `skills/scene_context_inspector/` elaborate but mostly unused | Deleted unless one becomes the baseline-builder | Decide and act |
| Docs | CLAUDE.md outdated, contradicts code; multiple stale architecture docs | One short operational CLAUDE.md + product_direction + agent1_core + this plan | Trim docs; archive or delete the rest |
| Language | Mixed PT/EN in code messages, prompts, knowledge, gate text | English-only canonical | Translate everything load-bearing |
| Server bug | `bump_turn_counter` called twice (server.py:427 + run_turn) | Called once | Fix in convergence step |
| Server bug | Literal `"conversation_surface_primary": "chatgpt"` in server.py:192 | Removed | Delete |

---

## 4. Refactor Workstreams

Ten workstreams. Some run in parallel, some are sequential. Ordering in §11.

### Workstream A — Session Schema Foundation
**Goal:** Replace the flat dict with the structured schema (§7).
**Scope:** `session_store.py`, every reader/writer of session state, persistence file format, schema version migration from 0.1 to 1.0.
**Output:** `session/schema.py` (dataclasses), `session/store.py` (load/save/migrate), `session/baseline.py` (baseline_workspace logic).
**Dependencies:** None — this is the foundation.

### Workstream B — Runtime Convergence
**Goal:** One central `Runtime`, no parallel implementations.
**Scope:** `agent_runtime.py`, `server.py` (in-addon), `blender_connection.py`, root `server.py`.
**Output:** `runtime/core.py` as the single owning class. Both chat UI and MCP adapt.
**Dependencies:** Workstream A complete (so both paths can share session).

### Workstream C — Turn Router
**Goal:** Replace `run_turn`'s 12-stage pipeline with the 9-class router (§8).
**Scope:** `runtime_turn.py`, `runtime_planning.py`, `runtime_governance.py` (most of it).
**Output:** `runtime/router.py` (classifier + dispatch), `runtime/handlers/` (one file per turn class), `runtime/state_machine.py` (execution_state.phase transitions).
**Dependencies:** Workstreams A and B.

### Workstream D — Approval State Machine
**Goal:** State-dependent approval, no tokens, no keyword matching.
**Scope:** `_EXECUTION_RESUME_KEYWORDS`, `runtime_governance.py`, `execution_prechecks.py`, plan/approval token generation, all `_render_plan_approval_message` paths.
**Output:** `runtime/state_machine.py` (shared with Workstream C). All approval logic lives here.
**Dependencies:** Workstream C in flight.

### Workstream E — Knowledge Retrieval
**Goal:** Replace keyword-driven knowledge selection with structural/focus/intent-driven retrieval.
**Scope:** `context_knowledge.py`, `context_skills.py`, `knowledge/` directory layout, recipe format.
**Output:** `knowledge/retriever.py`, recipe schema, English-only consolidated corpus.
**Dependencies:** Workstream A (needs `focus` and `baseline_workspace`).

### Workstream F — Failure Policy
**Goal:** One-shot explain-and-stop. No replan loops.
**Scope:** `execution_postprocess.py`, `build_replan_payload`, fallback plan and approval logic.
**Output:** Simplified post-execution flow inside the dispatcher; explanation builder.
**Dependencies:** Workstream D (state machine owns the post-failure transition).

### Workstream G — Dispatcher Consolidation
**Goal:** One execution surface. Merge `runtime_dispatch.py` + `execution_dispatch.py` + relevant parts of `tools.py` and `safety_policy.py`.
**Scope:** Both dispatch files, the safety policy file, the precheck file.
**Output:** `execution/dispatcher.py`, `execution/tools.py` (registry), `execution/handlers.py` (per-tool implementations).
**Dependencies:** Workstreams B and D.

### Workstream H — UI Layering
**Goal:** Chat panel speaks in prose first, details on demand. No second API call.
**Scope:** `chat_ui.py`, the plan rendering pipeline, the conversationalization API call.
**Output:** Refactored `ui/panel.py`, `ui/chat_session.py`, `ui/screenshot.py`. Default surface is minimal; advanced controls collapse.
**Dependencies:** Workstreams C and D (UI needs the new turn classes and phase enum to know what to render).

### Workstream I — Cleanup and Translation
**Goal:** Delete dead surfaces, translate to English, fix the doc/code mismatch.
**Scope:** `snapshots/`, `reference/`, `blender_mcp_package/`, `skill_router.py`, `safety_policy.py`, `contracts/` (decide), `skills/` (decide), legacy docs, all PT messages and gate text.
**Output:** Smaller repo, one canonical language, accurate CLAUDE.md.
**Dependencies:** Can start in parallel with Workstream A. Some deletions happen earlier, some after the runtime convergence proves nothing important is lost.

### Workstream J — Testing
**Goal:** A real test layer matched to the new turn classes and state machine.
**Scope:** Currently almost no tests. Build minimal smoke + state-machine + classifier tests.
**Output:** `tests/` with: turn classifier tests, state machine transition tests, baseline retrieval tests, dispatcher contract tests, end-to-end runtime smoke test using a fake Blender.
**Dependencies:** Workstreams A, C, D — the things being tested must exist first.

---

## 5. New Proposed File / Module Shape

Target tree under `blender_addon/`:

```
blender_addon/
├── __init__.py                  # addon registration only
│
├── runtime/
│   ├── __init__.py
│   ├── core.py                  # Runtime: owns session, router, dispatcher, journal
│   ├── router.py                # TurnRouter: classify + dispatch
│   ├── state_machine.py         # ExecutionStateMachine: phase enum + transitions
│   ├── prompt_builder.py        # build_system_prompt (compact, baseline-driven)
│   └── handlers/
│       ├── __init__.py
│       ├── greeting.py
│       ├── clarification.py
│       ├── diagnosis.py
│       ├── baseline_refresh.py
│       ├── proposal.py
│       ├── mutation_request.py
│       ├── mutation_confirmation.py
│       ├── mutation_denial.py
│       └── post_failure.py
│
├── session/
│   ├── __init__.py
│   ├── schema.py                # Session, Identity, Focus, BaselineWorkspace, etc.
│   ├── store.py                 # load/save/migrate, per-blend persistence
│   ├── baseline.py              # baseline_workspace builder + staleness check
│   └── history.py               # bounded chat history
│
├── execution/
│   ├── __init__.py
│   ├── dispatcher.py            # single tool execution surface
│   ├── tools.py                 # tool registry (consolidates current tools.py)
│   ├── handlers.py              # per-tool implementations
│   └── code_runner.py           # execute_code specifics
│
├── knowledge/
│   ├── __init__.py
│   ├── retriever.py             # focus + baseline + structural -> ranked context
│   ├── recipe_loader.py         # loads recipes/ as named structural patterns
│   └── learned.py               # learned_patterns.md updater (current behavior preserved)
│
├── ui/
│   ├── __init__.py
│   ├── panel.py                 # Blender panel definition, layered surface
│   ├── chat_session.py          # in-memory chat session, daemon thread, screenshot
│   ├── screenshot.py            # PowerShell + SnippingTool capture
│   └── advanced.py              # collapsible advanced controls
│
├── transport/
│   ├── __init__.py
│   ├── server.py                # in-addon TCP server, thin wrapper around Runtime
│   └── capture.py               # scene/GN snapshot helpers (current capture.py)
│
└── journal.py                   # operation_journal.py renamed, unchanged in shape
```

Top of repo:

```
.
├── REFATOR_PLAN.md              # this file
├── QUESTIONS.md                 # the prior architectural review
├── CLAUDE.md                    # short operational entrypoint (rewritten)
├── README.md                    # short product description
│
├── blender_addon/               # see above
│
├── mcp/
│   ├── __init__.py
│   ├── server.py                # FastMCP adapter, calls into runtime
│   └── connection.py            # was blender_connection.py
│
├── knowledge/
│   ├── recipes/                 # English-only canonical recipes
│   ├── domain/                  # English-only canonical domain references
│   └── learned_patterns.md      # auto-grown
│
├── docs/
│   ├── product_direction.md
│   ├── agent1_core.md
│   └── archive/                 # everything else, frozen, not authoritative
│
└── tests/
    ├── classifier/
    ├── state_machine/
    ├── baseline/
    ├── dispatcher/
    └── smoke/
```

What is gone from the tree:

- `blender_addon/agent_runtime.py` (logic moves into `runtime/`)
- `blender_addon/runtime_turn.py`, `runtime_planning.py`, `runtime_governance.py`, `runtime_dispatch.py`, `runtime_state_sync.py`, `execution_dispatch.py`, `execution_prechecks.py`, `execution_postprocess.py`, `runtime_execution.py`, `context_prompt.py`, `context_knowledge.py`, `context_skills.py`, `context_continuity.py` and similar — all consolidated into the new `runtime/`, `execution/`, `knowledge/` packages
- `blender_addon/safety_policy.py`
- `blender_addon/skill_router.py`
- `snapshots/`
- `reference/`
- `blender_mcp_package/`
- Root `server.py` (replaced by `mcp/server.py`)
- `blender_connection.py` (replaced by `mcp/connection.py`)

---

## 6. Removal / Merge / Rename Candidates

### 6.1 Delete outright

| Path | Reason |
|---|---|
| `snapshots/` | Whole-codebase copies. Use git. |
| `reference/` | Old project. Already noted in CLAUDE.md as not for runtime. Consult upstream repo if needed. |
| `blender_mcp_package/` | Duplicates knowledge files. Unclear ownership. |
| `blender_addon/skill_router.py` | CLAUDE.md says do not recreate; it exists anyway. |
| `blender_addon/safety_policy.py` | CLAUDE.md says do not recreate; meaningful checks fold into dispatcher. |
| `_EXECUTION_RESUME_KEYWORDS` regex | Brittle keyword approval. Replaced by state machine. |
| `_render_plan_approval_message` | UI-hostile plan dump. |
| `_request_conversational_plan_response` | Extra API call to wrap a previous response. |
| `build_replan_payload` and surrounding fallback infra | Recursive replan loop. Delete entirely. |
| Plan/approval token generation (`plan-{uuid}`, `appr-{uuid}`) | Tokens leave the system. |
| Stage normalization, per-stage approval | Stages disappear as a concept. |
| `context_plan` as artifact | Reads do not produce plans. |
| `presented_plan_*` fields in session state | Replaced by structured `execution_state` and `proposal` payloads. |
| `legacy_chat_history_enabled` flag and dual-history sync | Single bounded history in `session.history`. |
| `bump_turn_counter` second call site in `server.py` | Bug; counted twice. |
| `"conversation_surface_primary": "chatgpt"` literal | Bug/leftover. |
| Most files under `docs/` other than `product_direction.md`, `agent1_core.md`, `refactor_plan_ui_copilot.md`, `README.md` | Stale architecture maps. Move to `docs/archive/`. |
| `arquitetura_agentes.md`, `prompt_claude_code.md`, mixed-language design notes | Out of date and superseded by this plan. |

### 6.2 Decide-then-act (kept only if it earns its keep)

| Path | Decision criterion |
|---|---|
| `contracts/` JSON schemas | Keep only if wired into the dispatcher to validate tool inputs/outputs. Otherwise delete. |
| `skills/gn_scene_state_interpreter/` | Keep only if it becomes the baseline-builder (see Workstream A). Otherwise delete. |
| `skills/scene_context_inspector/` | Same criterion. |
| `mcp/` adapter | Keep through Phase 6. If the Blender UI remains the only meaningfully used surface, remove in Phase 8. |

### 6.3 Merge

| Sources | Target |
|---|---|
| `runtime_dispatch.py` + `execution_dispatch.py` + parts of `tools.py` + parts of `safety_policy.py` | `execution/dispatcher.py` + `execution/tools.py` + `execution/handlers.py` |
| `runtime_turn.py` + `runtime_planning.py` + `runtime_governance.py` (turn-routing parts) | `runtime/router.py` + `runtime/handlers/*.py` + `runtime/state_machine.py` |
| `context_prompt.py` + `context_continuity.py` + parts of `context_knowledge.py` | `runtime/prompt_builder.py` + `knowledge/retriever.py` |
| `context_knowledge.py` + `context_skills.py` + `knowledge_updater.py` | `knowledge/retriever.py` + `knowledge/recipe_loader.py` + `knowledge/learned.py` |
| `agent_runtime.py` + `RuntimeBridgeCore` (server-side) | `runtime/core.py` |
| `chat_ui.py` (split) | `ui/panel.py`, `ui/chat_session.py`, `ui/screenshot.py`, `ui/advanced.py` |
| `blender_addon/server.py` + parts of `blender_connection.py` | `transport/server.py` + `mcp/connection.py` |
| Root `server.py` | `mcp/server.py` |

### 6.4 Rename

| From | To | Why |
|---|---|---|
| `operation_journal.py` | `journal.py` | Shorter, the only journal in the system. |
| `capture.py` | `transport/capture.py` | Lives next to the transport that uses it. |
| `knowledge_updater.py` | `knowledge/learned.py` | Clearer name; sits with the rest of knowledge. |
| `chat_ui.py` (whole module) | `ui/` package | The file has outgrown a single module. |

### 6.5 Demote

| Item | New status |
|---|---|
| `make_plan` tool | Optional. Used only when the model judges a multi-step mutation needs an explicit plan. No longer the universal first call. |
| `get_tree_structure` | Demoted relative to focused subgraph reads. Used only on baseline refresh or explicit "show whole tree" requests. |
| Debug/override/MCP-write toggles | Move under `Advanced` collapsible. Hidden by default. |
| `safety_policy` notion | Folds into the dispatcher as inline checks; not its own module, not its own concept. |

---

## 7. Session Schema Proposal

Single source of truth, persisted per `.blend` (or per focused modifier when meaningful), versioned, English keys, no flat sprawl.

```text
Session
├── identity
│   ├── session_id                (str, uuid)
│   ├── schema_version            (str, "1.0")
│   ├── created_at                (iso8601)
│   ├── last_active_at            (iso8601)
│   └── canonical_language        ("en")
│
├── focus
│   ├── blend_path                (str)
│   ├── object_name               (str | null)
│   ├── modifier_name             (str | null)
│   ├── tree_name                 (str | null)
│   ├── focus_signature           (str, hash of object+modifier+tree)
│   └── focus_changed_at          (iso8601)
│
├── baseline_workspace
│   ├── tree_signature            (str, structural hash)
│   ├── built_at                  (iso8601)
│   ├── built_from                ("auto" | "user_request" | "post_mutation")
│   ├── structural_summary        (object: counts, frames, groups, root io, depth)
│   ├── semantic_layers           (list: named regions of the graph + role)
│   ├── subgraph_index            (dict: name -> compact subgraph descriptor)
│   ├── recipe_associations       (list: recipe_id + match confidence)
│   ├── known_parameters          (dict: parameter name -> last seen value + role)
│   ├── open_questions            (list of strings — what the agent still does not know)
│   └── stale                     (bool — set true when tree changes since baseline)
│
├── history
│   ├── max_messages              (int, default 80)
│   ├── messages                  (list of {role, content, ts, turn_class})
│   └── older_summary             (str | null — rolling summary of evicted messages)
│
├── execution_state
│   ├── phase                     ("idle" | "reading" | "proposing" | "awaiting_confirmation" | "executing" | "failed" | "halted")
│   ├── pending_mutation          (object | null: what the agent proposed and is waiting on)
│   │     ├── description         (str, plain English)
│   │     ├── tool_calls          (list — internal, not surfaced)
│   │     ├── proposed_at         (iso8601)
│   │     ├── focus_signature     (str — invalidated if focus changes)
│   │     └── plan_used           (bool — whether make_plan was invoked)
│   ├── last_failure              (object | null: tool, error, cause, suggested_alternative)
│   └── consecutive_failures      (int — caps at 1 in this design; reserved for safety)
│
├── ui_state
│   ├── advanced_open             (bool)
│   ├── debug_mode                (bool)
│   ├── explicit_override_mode    (bool)
│   ├── mcp_write_enabled         (bool)
│   └── last_screenshot_meta      (object | null)
│
└── lifecycle
    ├── continuity_token          (str — opaque, used to reattach across restarts)
    ├── prior_session_ids         (list, bounded)
    └── notes                     (list — agent-authored continuity hints)
```

Key invariants:

1. **Approval lives only in `execution_state`.** Nothing else in the schema records "is the user approving something." There is exactly one `pending_mutation` slot.
2. **`pending_mutation` is invalidated automatically** when `focus.focus_signature` changes, when `baseline_workspace.stale` becomes true, or when a non-confirmation/non-denial turn class is dispatched.
3. **`baseline_workspace` is the persistent technical brain.** It is the thing the runtime asks "is this enough?" before reading more. It is rebuilt on demand, not on every turn.
4. **`history` is bounded and self-contained.** No sidecar dual-history, no `legacy_chat_history_enabled` flag.
5. **`identity.schema_version` exists.** Migration from current `0.1` flat dict to `1.0` is explicit and one-shot.
6. **No `presented_plan_*` fields.** Anything the model needs to remember about the last proposal is captured under `execution_state.pending_mutation` or `history`.

Persistence: one JSON file per `.blend` (current behavior) under the user's Blender config dir. Schema migration runs on load if `schema_version` is missing or `< 1.0`.

---

## 8. Runtime Turn Model Proposal

### 8.1 Pipeline (target)

```
incoming user message
        │
        ▼
┌─────────────────────────────┐
│ TurnRouter.classify         │   ← cheap: state inspection + lightweight signals
└─────────────┬───────────────┘
              │
              ▼
       turn_class (one of 9)
              │
              ▼
┌─────────────────────────────┐
│ runtime/handlers/<class>.py │   ← single handler runs the turn end-to-end
└─────────────┬───────────────┘
              │
              ▼
   tool calls (if any) → execution/dispatcher → journal
              │
              ▼
   state_machine.transition(...)
              │
              ▼
   response payload → ui/panel
```

No 12 stages. No precheck cascade. No replan loop. Each handler has direct authority over its turn and yields one response and at most one phase transition.

### 8.2 Classification rules

The classifier looks at, in order:

1. **`execution_state.phase`** — if `awaiting_confirmation`, the only candidate classes are `mutation_confirmation`, `mutation_denial`, or any class that explicitly invalidates the pending mutation (e.g., a fresh `mutation_request` for something different, or a `clarification` whose answer is unrelated).
2. **Trivial patterns** — greeting/thanks → `greeting_or_smalltalk`.
3. **Question shape** — interrogatives about the tree, nodes, scene, baseline → `diagnosis` or `clarification`.
4. **Imperative/proposal shape** — "set", "wire", "make", "remove", "rebuild" → `mutation_request`. "How would you", "what's the smallest" → `proposal`.
5. **Staleness check** — if the chosen class needs the baseline and the baseline is stale (`baseline_workspace.stale == true`), the router prefixes a `baseline_refresh` step before dispatching.
6. **Default** — `clarification`, the safest no-op class.

The classifier never makes an LLM call. If the classification is genuinely ambiguous, the runtime defaults to the more conservative class (clarification over mutation, diagnosis over proposal).

### 8.3 Handler contracts

Each handler is a small, testable function with this shape:

```text
input:  Session, message, classifier_meta
output: HandlerResult {
            response_text: str,           # what the UI shows (already layered)
            tool_calls_made: list,        # for the journal
            phase_transition: enum | None,
            session_mutations: list       # changes to baseline_workspace, focus, etc.
        }
```

Handlers do not import each other. Cross-cutting concerns (knowledge retrieval, prompt building, dispatcher) are passed in via the central `Runtime`.

### 8.4 The "is the baseline sufficient" question

Every handler that needs structural understanding (diagnosis, proposal, mutation_request) starts by asking:

> Given the user's message and the current `focus`, is `baseline_workspace` sufficient to answer this without re-reading the tree?

If yes, proceed using only the baseline + the retriever's small bundle.
If no, the handler triggers a focused refresh of just the missing piece (typically a subgraph read), updates `baseline_workspace`, and proceeds.

This replaces the current "read everything every turn" tendency and the "context plan as a separate artifact" pattern.

### 8.5 What `make_plan` becomes

`make_plan` is one tool among many. It is invoked **only by the `mutation_request` handler**, **only when** the proposed change is multi-step or risky enough that an explicit plan helps the user reason about it. Reads, diagnosis, conversation, baseline refreshes, and trivial mutations never call `make_plan`. The plan, when produced, is a concise English summary in the response, not a stage machine.

### 8.6 What execution feels like

```
user: set VM_G1_Scale to 1.0
        │
        ▼
classifier: mutation_request
        │
        ▼
handler:
  - confirms baseline knows the node
  - reads node context (no plan needed)
  - prepares execute_code payload
  - presents:
       "I'll set VM_G1_Scale to 1.0. This affects only the
        scale parameter in the focused tree. Confirm?"
  - phase: idle → awaiting_confirmation
  - stores pending_mutation
```

```
user: yes
        │
        ▼
classifier: state is awaiting_confirmation, message is affirmative
            → mutation_confirmation
        │
        ▼
handler:
  - calls dispatcher with the stored payload
  - one attempt
  - on success: phase → idle, baseline updated, journal recorded,
                response: "Done. VM_G1_Scale is now 1.0."
  - on failure: phase → failed, response: "I tried X, got Y, likely
                because Z. Want me to try W instead?"
                NO replan, NO retry
```

```
user: what does this tree do?
        │
        ▼
classifier: diagnosis
        │
        ▼
handler:
  - baseline check: sufficient? yes
  - retriever: pull recipe matches + relevant domain notes
  - response: prose explanation, "show details" expandable for the node listing
  - phase unchanged (idle)
```

---

## 9. Knowledge Architecture Proposal

### 9.1 Sources

- **Recipes** (`knowledge/recipes/*.md`) — named, structural, English. Each recipe has front-matter: id, title, applies_when (structural conditions), summary, references. Recipes are the central reference patterns the copilot leans on.
- **Domain notes** (`knowledge/domain/*.md`) — orthosis-specific concepts (G1 continuity, anchor placement, biomodel proxy), Geometry Nodes reference material. English.
- **Learned patterns** (`knowledge/learned_patterns.md`) — auto-grown by the Haiku-driven `knowledge/learned.py` after each successful goal. Behavior preserved from current `knowledge_updater.py`.
- **Skill folders** (`knowledge/skills/`, currently `skills/`) — only if any of them earn their keep as baseline builders. Otherwise removed.

### 9.2 Retrieval inputs

The retriever takes:

- the **focus** (object, modifier, tree)
- the current **baseline_workspace.tree_signature** and **structural_summary**
- the **turn class** and **classifier signals**
- the **user message**

It returns a small, ranked, token-budgeted set of:

- 0–2 matched recipes
- 0–2 relevant domain notes
- 0–1 learned-pattern entries

### 9.3 Ranking

Ranking is structural-first, intent-second, message-keyword-last:

1. **Structural similarity** — recipes whose `applies_when` matches the current `tree_signature` and `structural_summary` rank highest.
2. **Focus tags** — recipes/domain-notes tagged for the current modifier kind.
3. **Intent fit** — proposal turns favor recipes; diagnosis turns favor domain notes; mutation turns favor whichever recipe most closely matches the change.
4. **Keyword overlap** — used as a tiebreaker only, not a primary signal.

The current regex keyword matcher is replaced wholesale.

### 9.4 Token discipline

Each retrieved item is summarized to a budgeted slice (e.g., 800 chars) before injection. The total knowledge budget per turn is bounded (e.g., 2K characters), and the prompt builder enforces it. No more 4×1400 dump.

### 9.5 Corpus consolidation

- Translate every Portuguese knowledge file in `knowledge/` to English.
- Delete duplicates living in `blender_mcp_package/`.
- Enforce front-matter schema for recipes.
- Add a one-time `knowledge/INDEX.md` describing the corpus shape (regenerable, not a hand-maintained map).

---

## 10. Testing Refactor Plan

The current repo has effectively no automated tests. The refactor adds a small, targeted test layer. Not exhaustive — sufficient.

### 10.1 Layers

| Layer | Tests | Why |
|---|---|---|
| **Unit: classifier** | Given (session phase, message), assert turn class | The router is the heart of the new design; regressions are catastrophic. |
| **Unit: state machine** | Each phase transition, each invalidation rule | Approval correctness depends entirely on this. |
| **Unit: baseline** | Build, refresh, staleness detection | The "is the baseline sufficient" question depends on this. |
| **Unit: retriever** | Given (focus, baseline, intent), assert ranked top-k | Knowledge selection is no longer keyword-based; verify it. |
| **Contract: dispatcher** | For each tool, given a sample input, assert serialization shape and that the journal records the call | Avoid silent tool drift. |
| **Smoke: runtime** | End-to-end turn through a fake Blender stub: greeting, diagnosis, mutation_request → confirmation → success, mutation_request → confirmation → failure (explain-only) | Catches integration regressions in the loop. |

### 10.2 Out of scope (intentionally)

- No test of Blender Python API behavior. Use fakes/stubs.
- No test of the LLM output. Mock the API client.
- No coverage threshold. Tests exist to defend the invariants, not to inflate metrics.

### 10.3 Where tests live

Top-level `tests/` mirroring the new package structure. Smoke runs are gated behind a fake-Blender fixture so they can run on any machine.

### 10.4 Pre-existing manual checks

The four-step manual sequence in CLAUDE.md ("qual o estado atual da cena?" through `learned_patterns.md` update) is converted into an English-language smoke script, kept as `tests/smoke/manual_blender.md`, and updated to match the new turn classes and approval state machine.

---

## 11. Implementation Order

Nine phases. Each phase delivers a runnable system. No phase leaves the runtime in an unrunnable state.

### Phase 0 — Prep
- Freeze the current `agent_runtime.py` / `runtime_*.py` behavior as a baseline branch.
- Move stale docs into `docs/archive/`.
- Add `.gitignore` entry for `snapshots/`.
- Delete `snapshots/`, `reference/`, `blender_mcp_package/` (Workstream I, first wave).
- Rewrite CLAUDE.md as a short, accurate operational entrypoint that points at this plan.

### Phase 1 — Session Foundation (Workstream A)
- Implement `session/schema.py`, `session/store.py`, `session/baseline.py`, `session/history.py`.
- Build the migration from the existing flat dict to the structured schema.
- Plumb the new schema behind a feature flag in the existing `agent_runtime.py` so both old and new state can coexist briefly.
- Tests: schema construction, persistence round-trip, migration from `0.1`.

### Phase 2 — Runtime Convergence (Workstream B)
- Create `runtime/core.py`. Move `AgentRuntime` responsibilities into it.
- Reroute the in-Blender `transport/server.py` to call `Runtime.handle_socket_call` instead of `RuntimeBridgeCore`.
- Delete `RuntimeBridgeCore` and the literal `"chatgpt"` bug.
- Fix the double `bump_turn_counter` bug by centralizing it in `Runtime.run_turn`.
- Tests: smoke test that both the chat path and the socket path produce identical responses for the same input.

### Phase 3 — Turn Router and Handlers (Workstream C)
- Implement `runtime/router.py` and `runtime/state_machine.py`.
- Implement the nine handlers in `runtime/handlers/`.
- Implement `runtime/prompt_builder.py` with the compact prompt format.
- Migrate `agent_runtime.run_turn` to delegate to the router. Delete the 12-stage pipeline in `runtime_turn.py`.
- Tests: classifier, state machine, prompt builder size budget.

### Phase 4 — Approval State Machine (Workstream D)
- Wire approval entirely through `execution_state.phase`.
- Delete `_EXECUTION_RESUME_KEYWORDS`, plan/approval token generation, `_render_plan_approval_message`, `_request_conversational_plan_response`.
- Delete the precheck cascade in `execution_prechecks.py` (keep only the dispatcher-level safety inline checks that survive into Phase 5).
- Tests: every transition rule, every invalidation rule.

### Phase 5 — Dispatcher Consolidation (Workstream G)
- Merge `runtime_dispatch.py`, `execution_dispatch.py`, `tools.py`, and the meaningful parts of `safety_policy.py` into `execution/dispatcher.py` + `execution/tools.py` + `execution/handlers.py`.
- Delete `safety_policy.py` and `skill_router.py`.
- Tests: dispatcher contract for each tool.

### Phase 6 — Knowledge Retrieval (Workstream E)
- Implement `knowledge/retriever.py`, `knowledge/recipe_loader.py`, `knowledge/learned.py`.
- Translate the corpus to English.
- Add front-matter to recipes; add `applies_when` conditions.
- Delete the keyword regex selector.
- Tests: retriever ranking on representative baselines.

### Phase 7 — Failure Policy (Workstream F)
- Replace `execution_postprocess.py` with the explain-and-stop flow.
- Delete `build_replan_payload`, fallback plan, fallback approval token, `consecutive_failures` retry behavior.
- Tests: failed mutation produces explain-only response and `phase = failed`; subsequent user message resets to `idle` cleanly.

### Phase 8 — UI Layering (Workstream H)
- Split `chat_ui.py` into `ui/panel.py`, `ui/chat_session.py`, `ui/screenshot.py`, `ui/advanced.py`.
- Replace plan-dump rendering with prose-first + expandable details.
- Move debug/override/mcp-write toggles into `ui/advanced.py`.
- Delete the second-API-call conversationalization step.
- Tests: smoke that the UI renders the expected layers for each turn class.

### Phase 9 — MCP Decision and Cleanup (Workstreams I, J finalization)
- Move `server.py` (root) and `blender_connection.py` to `mcp/`. Rewrite as a thin adapter calling `Runtime`.
- Decide whether MCP stays. If retained: keep thin and audit dead surface. If removed: delete `mcp/` and update docs.
- Final cleanup pass: dead imports, unused fields, archive remaining stale docs, run all tests, update CLAUDE.md to reflect final shape.

---

## 11.1 Current Overlay — 2026-04-30 Blender Validation

This section records the live implementation state after the Onda 4.E manual Blender validation. It supersedes older "pending validation" notes in handoff conversations.

### Onda 4.E Status

Validation target: prove that the agent starts important turns with usable Geometry Nodes tree context, and that missing structural memory fails visibly in the journal rather than silently degrading UX.

| Item | Journal evidence | Status |
|---|---|---|
| 1 — Tree render in system prompt for factual tree inquiry | `tree_prompt_render_injected` with `marker_node_names_count > 0` | Passed |
| 3 — First draft turn after Blender reopen starts with tree context | `tree_prompt_render_injected` + `baseline_workspace_rebuilt` before draft write; `script_draft_write_succeeded` | Passed behaviorally |
| 2 — Structural-memory/bridge failure is visible | `simulate_bridge_failure_active` then `structural_memory_recovery_failed` with non-empty `reason` | Passed |

Validated runs:

- `run-20260430T191720Z-bb9dd970`: factual inquiry injected tree render for `Biomodelo`, `node_count=80`, `marker_node_names_count=80`.
- `run-20260430T194733Z-371620ea`: clean first draft prompt after Blender reopen injected tree render, rebuilt baseline, and saved `GN_Agent_Draft` revision 12.
- `run-20260430T202014Z-cd0a8fd5`: `Simulate Bridge Failure` path logged `structural_memory_recovery_failed.reason = "Simulated bridge failure: debug flag simulate_bridge_failure is enabled."`

Nuance for Item 3: a clean draft turn may reuse fresh persisted structural memory rather than calling `build_tree_structural_memory` in that exact run. That is accepted if `tree_prompt_render_injected` and `baseline_workspace_rebuilt` occur before the draft write. The UX requirement is "agent starts with tree context without a warm-up turn", not "always rebuild from Blender even when cache is fresh".

### UX Fixes Landed During Validation

- Factual tree questions in `drafting` route as read-only context inquiries and no longer inherit stale draft diagnostics from chat history.
- Answer-correction messages in drafting are treated as inquiry/correction context instead of falling into a useless "did not write draft" response.
- `write_script_draft` semantic-regression blocks now return detailed payloads to the model and allow one in-turn self-correction before reporting failure.
- The loop still stops immediately after a successful draft write.
- Diagnosis/read-only responses preserve useful analysis instead of replacing it with "no draft was saved" when no write was requested.
- `Advanced / Debug` now includes `Simulate Bridge Failure`; the flag is persisted in `UIState` V1 and exists only for validation/debugging.

### Next Gate

Onda 5 may start. Keep Onda 6/router refactor available if UX regressions continue, but the three Onda 4.E journal checks are now closed.

---

## 12. "Do Not Preserve" List

The following are explicitly out of scope for preservation. They should be removed, not refactored, not migrated, not maintained behind feature flags.

1. **`ALWAYS_PLAN_FIRST = True` and the `make_plan`-as-first-tool requirement.** Reads, diagnosis, and conversation will never plan. Mutations may, when they earn it.
2. **The 12-stage pipeline in `runtime_turn.run_turn`.** Replaced by the turn router.
3. **`_EXECUTION_RESUME_KEYWORDS`.** Brittle keyword approval. Replaced by state-machine matching inside `mutation_confirmation`.
4. **Approval tokens (`appr-{uuid}`) and plan tokens (`plan-{uuid}`) in any user-visible surface.** Tokens are an implementation detail at most, never UX.
5. **Per-stage approval ceremony.** Stages disappear. A mutation has a single confirmation gate.
6. **Context plans as formal artifacts.** Reads are conversational. There is no `presented_context_*` blob.
7. **`_request_conversational_plan_response` and any second API call to wrap a previous response.** One API call per turn.
8. **`_render_plan_approval_message`.** No 20-line plan dump as the primary message.
9. **`build_replan_payload` and the recursive replan loop.** One failure → explain-and-stop.
10. **Fallback plan + fallback approval token infrastructure.** Same reason.
11. **`AgentRuntime` and `RuntimeBridgeCore` as parallel runtimes.** One central `Runtime`.
12. **`safety_policy.py` as a separate module and concept.** Folds into the dispatcher.
13. **`skill_router.py`.** Already disallowed by CLAUDE.md; remove for real.
14. **The flat 50-key session dict in `_default_state`.** Replaced by the structured schema.
15. **`presented_plan_*`, `current_plan_*`, `execution_plan_*`, `fallback_plan_*` keys.** Replaced by `execution_state.pending_mutation`.
16. **`legacy_chat_history_enabled` flag and dual-history sync.** One bounded history in the schema.
17. **Regex keyword knowledge selection in `context_knowledge.py`.** Replaced by structural retrieval.
18. **The 4×1400 + 4×1200 prompt knowledge dump in `context_prompt.build_system_prompt`.** Replaced by budgeted retriever output.
19. **The `"conversation_surface_primary": "chatgpt"` literal in `server.py`.** Bug/leftover.
20. **The double `bump_turn_counter` call in `server.py:427`.** Bug.
21. **`snapshots/`, `reference/`, `blender_mcp_package/`.** Dead surfaces.
22. **Mixed Portuguese/English in code messages, prompts, gate text, knowledge, journal labels, and docs.** English is the canonical language.
23. **Stale documentation files outside `product_direction.md`, `agent1_core.md`, `refactor_plan_ui_copilot.md`, `README.md`, `CLAUDE.md`, this plan, and `QUESTIONS.md`.** Move to `docs/archive/`.
24. **MCP as a parallel cognition path.** It either becomes a thin adapter or it goes away.
25. **`make_plan` as a synonym for "the agent is going to do something".** It is just a tool the model may use when an explicit multi-step plan helps the user reason.
26. **Stage normalization, plan-type inference, plan-mode inference, plan-gate logic.** These concepts disappear with the pipeline.
27. **Approval gates blocking read tools.** Reads are always free.
28. **The `skills/` directory in its current shape**, unless one of its components is repurposed as the baseline builder. Default is delete.
29. **`contracts/` JSON schemas**, unless wired into the dispatcher's input/output validation. Default is delete.
30. **Any architectural ambition described as "five agents", "verifier", "skill router", or "workflow engine".** The product is one technical copilot. The code should not encode anything else.

---

*End of REFATOR_PLAN.md.*
