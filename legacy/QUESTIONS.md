# QUESTIONS.md — Architectural Review (v2)

> Generated 2026-04-04 by senior code reviewer (Claude Opus 4.6).
> Supersedes the previous QUESTIONS.md from 2026-04-02.
> Answer each question, then we proceed to implementation.

---

## Executive Summary

The codebase has grown significantly since the original monolithic `agent_runtime.py`. The refactoring into `runtime_turn`, `runtime_planning`, `runtime_governance`, `runtime_execution`, `execution_prechecks`, `execution_dispatch`, `execution_postprocess`, `context_knowledge`, `context_prompt`, `context_skills`, and `runtime_state_sync` was a meaningful structural improvement. However, the product intent described in `docs/product_direction.md` and `docs/agent1_core.md` — a conversational copilot that understands first, explains second, and proposes the smallest useful next step — has drifted significantly from what the code actually does. The code still behaves like a formal governance/workflow engine with heavy ceremony around every turn.

Key tensions:

1. **Product vs. Implementation**: The docs say "copilot, not workflow engine." The code requires a plan + approval + staged execution + governance tokens for every non-conversation turn, including simple reads and diagnostics.

2. **Approval ceremony vs. fluidity**: Every turn that isn't purely conversational goes through plan creation → approval gate → blocked message → user approval → execution. This contradicts the CLAUDE.md rule "Não pedir confirmação para operações de GN."

3. **Dual runtime paths**: `AgentRuntime` (used by chat_ui) and `RuntimeBridgeCore` (used by server.py for MCP) are two parallel runtime implementations with duplicated logic for project root resolution, session management, plan rebuilding, and state inference.

4. **CLAUDE.md stale vs. actual code**: CLAUDE.md describes 6 tools and a simpler architecture. The actual code has 27+ tools, ~15 runtime modules, and a completely different flow.

5. **Module explosion**: The original monolith was broken into many small files, but the conceptual complexity was preserved — it just moved across files. `runtime_planning.py` alone is 1574 lines.

6. **Files that CLAUDE.md says "do not recreate" exist**: `skill_router.py` and `safety_policy.py` both exist despite CLAUDE.md explicitly saying not to recreate them.

---

## 1. Product Direction

### Q1.1 — The approval-for-everything flow contradicts the copilot identity

The product direction says "propose the smallest useful next step" and "the experience should feel like a technical partner in the node editor, not like a workflow engine." But `run_turn()` creates a formal plan with stages, approval tokens, and governance logging for *every* non-conversation turn — including a simple `get_node_context` read.

**Why this matters:** A user who asks "mostra o contexto do nó X" will get a multi-paragraph plan presentation in Portuguese asking for approval before a single read-only tool executes. This is the opposite of a copilot.

**Category:** Design debt / product-implementation mismatch
**Files:** `runtime_turn.py:680-830`, `execution_prechecks.py:123-153`

Yes — this critique is valid. The current runtime applies too much formal planning and approval ceremony to turns that should feel lightweight, especially read-only and diagnostic interactions. That behavior is misaligned with the intended product direction of a technical copilot.

The intended direction is not a workflow engine that formalizes every non-conversational turn. The intended direction is a contextual technical copilot for Blender and Geometry Nodes, whose primary value is to understand the scene, explain the logic, diagnose structure, and propose the smallest useful next step.

That said, the solution is not simply to remove structure altogether. In this project, useful diagnosis depends on context acquisition, and context acquisition itself can become expensive in both tool calls and token usage. The real design goal is therefore:

to acquire only the minimum context necessary to be useful,
to treat scene understanding as primary,
to preserve that understanding across the session, and
to reserve heavier execution or governance flows for cases that truly require them.

For this reason, the system should be organized around session-level understanding of the GN modifier in focus, rather than rebuilding full understanding from scratch on every turn. Each session should establish a structural baseline for the active object / active GN modifier / active tree, then update that baseline incrementally as changes are made. Full-tree inspection should serve as a baseline-establishing or baseline-refreshing step, not as the default behavior for every interaction.

In practice, this means that read-only inspection, diagnosis, and explanation should become much more fluid. The agent should be able to answer questions, explain local logic, and suggest small next steps using the existing session baseline whenever possible. Expensive full-context tools should be used selectively, mainly when the baseline does not yet exist, when the focus changes, or when the tree has changed enough that the prior structural understanding is no longer reliable.

The preferred interaction model is also collaborative rather than executor-first. In many cases, the best next step is for the agent to explain what should be built, which nodes are relevant, how they should be connected, and what logic is being implemented, so the user can build and test interactively. Tool-driven mutation remains valuable, but it should be treated as secondary and invoked only when it provides real benefit.

So the decision for Q1.1 is:

The product should behave as a contextual copilot, not as a workflow engine for every turn. Read-only and diagnostic turns should not trigger the full plan/approval ceremony by default. Instead, they should rely on a persistent session baseline for the GN modifier in focus, with incremental context updates and selective use of heavier context tools only when needed.


### Q1.2 — CLAUDE.md says "Não pedir confirmação para operações de GN" but MUTATION_REQUIRES_USER_APPROVAL = True

CLAUDE.md rule #3 under autonomy says the agent should "Executar GN autonomamente — sem pedir confirmação." But `agent_runtime.py:142` sets `MUTATION_REQUIRES_USER_APPROVAL = True`, and the entire governance system enforces this. Which is the intended behavior?

**Why this matters:** This is a direct contradiction between the project's own documented philosophy and the runtime constants.

**Category:** Contradiction
**Files:** `agent_runtime.py:139-142`, `CLAUDE.md`

The intended policy is now clear: for Geometry Nodes, read-only inspection and diagnosis should be autonomous, but mutations should always require explicit user confirmation.

So the contradiction identified in this question is real. The problem is not that the runtime requires approval for mutations; the problem is that the wording in CLAUDE.md is too broad and no longer reflects the intended behavior accurately. “Do not ask for confirmation for GN operations” collapses together two very different categories of behavior:

inspection / diagnosis / explanation, and
mutation / structural change.

Those categories should not share the same approval policy.

For this product, GN inspection is central to the copilot experience. The agent should be able to inspect the active modifier, read structure, explain logic, identify relevant nodes, and reason about the current tree without requiring confirmation. That is necessary for fluid collaboration and aligns with the intended role of the system as a contextual technical copilot.

GN mutation is different. Even when the request is clear, node creation, rewiring, deletion, parameter changes, or structural edits should still require explicit user confirmation. The goal is not full autonomous construction by default, but a collaborative workflow in which the agent can understand first, explain second, propose the next step, and mutate only when the user explicitly authorizes it.

So the resolution is:

MUTATION_REQUIRES_USER_APPROVAL = True is aligned with the intended behavior for mutations. The outdated part is the wording in CLAUDE.md, which should be revised to state that GN inspection is autonomous, while GN mutation always requires confirmation.


### Q1.3 — CLAUDE.md file listing is stale

CLAUDE.md lists 8 files in `blender_addon/`. The actual directory has 22 Python files. Files like `runtime_turn.py`, `runtime_planning.py`, `runtime_governance.py`, `context_knowledge.py`, `context_prompt.py`, `context_skills.py`, `execution_dispatch.py`, `execution_prechecks.py`, `execution_postprocess.py`, `runtime_agent_loop.py`, `runtime_api_client.py`, `runtime_context.py`, `runtime_state_sync.py`, and `runtime_dispatch.py` are not documented.

**Why this matters:** CLAUDE.md is the primary navigation aid for the project. If it's stale, any LLM or developer reading it will make wrong assumptions about the architecture.

**Category:** Documentation debt
**Files:** `CLAUDE.md`

Yes — this critique is valid. CLAUDE.md is currently stale, and that is especially problematic because its primary audience is not a human maintainer reading casually, but Claude Code and Codex using it as an operational entrypoint into the project.

That means CLAUDE.md should not try to serve as a full architectural record, a historical archive, and a future vision document all at once. When it does, it becomes misleading. In its current state, outdated file listings, outdated tool counts, and outdated behavioral rules create exactly that problem: the file no longer provides a reliable mental model of the codebase that the agent is actually operating inside.

The intended role of CLAUDE.md going forward is therefore narrower and more disciplined:

it should be a short operational file,
primarily written for Claude Code / Codex,
and used as a portal to deeper documentation, not as the place where the full architecture is exhaustively described.

Its job is to communicate the active rules, the current high-level structure, the important constraints, and the correct pointers to deeper docs. It should help an agent enter the codebase with the right operational assumptions, not force the agent to infer which parts are still true and which parts are historical residue.

To avoid future drift, the file should also make a clear distinction between:

current architecture / current behavior, and
target direction / planned evolution.

Those two should both be visible, but explicitly separated. The current state should reflect what actually exists in code today. The future direction should summarize where the project is heading, while pointing to dedicated design documents for details.

So the resolution for Q1.3 is:

CLAUDE.md should be rewritten as a short operational entrypoint for Claude Code / Codex, with accurate current-state guidance, clearly separated target-direction notes, and links to deeper architecture/product docs. It should no longer attempt to act as the full source of architectural truth by itself.


### Q1.4 — CLAUDE.md says "Não recriar skill_router.py" and "Não recriar safety_policy.py" — but both exist

Both files are present in `blender_addon/`. Were they recreated deliberately, or did the "do not recreate" instruction become stale?

**Why this matters:** If these files are intentional, CLAUDE.md needs updating. If they were recreated by accident during refactoring, they should be evaluated.

**Category:** Ambiguity
**Files:** `blender_addon/skill_router.py`, `blender_addon/safety_policy.py`, `CLAUDE.md`

Yes — this inconsistency is real, but the most likely problem is not the current existence of these files. The more likely problem is that the instruction in CLAUDE.md has become stale and no longer reflects the architecture as it exists today.

Based on the current code, both files appear to have legitimate runtime roles.

skill_router.py functions as a thin adapter between the runtime and the analytical skills layer. It resolves the project root, makes the skills/ package importable, and exposes compact runtime-facing entrypoints such as analyze_scene(...) and analyze_gn_state(...), rather than acting as an independent orchestration layer.

safety_policy.py is even more clearly intentional in the current architecture. It centralizes runtime safety classification for both product and MCP routes, distinguishes between auto_apply, confirm_then_apply, and explicit_override, and already encodes the same high-level policy direction that the project is now clarifying: inspection-oriented tools may run more freely, while mutation-oriented tools require stronger gating.

So the best interpretation is:

the reviewer is correct that there is a documentation contradiction,
but the contradiction should not be resolved by assuming these files were recreated accidentally,
rather, it should be resolved by updating CLAUDE.md so it accurately reflects the current architecture and the intended role of these modules.

That does not prevent future refactoring. Either file may later be simplified, renamed, or absorbed into a different structure. But at present, both appear intentional and functionally relevant, so the documentation should be updated accordingly rather than treating their existence as an error by default.


### Q1.5 — The docs describe 5 agents (arquitetura_agentes.md) but the code implements only 1

`arquitetura_agentes.md` describes Agents 0-4, each with a specialized phase. The actual code has a single `AgentRuntime` class. Is the multi-agent architecture still the long-term direction, or has it been superseded by the single-copilot model described in `docs/agent1_core.md`?

**Why this matters:** If multi-agent is still intended, the current architecture needs to be designed for agent handoff. If it's abandoned, `arquitetura_agentes.md` and `prompt_claude_code.md` are misleading artifacts.

**Category:** Missing decision
**Files:** `arquitetura_agentes.md`, `docs/agent1_core.md`, `prompt_claude_code.md`

At this stage, the multi-agent documents should be treated primarily as a conceptual decomposition of responsibilities, not as a literal near-term implementation plan.

The current implementation direction is converging toward a single contextual copilot with a shared runtime, persistent session understanding, and differentiated internal responsibilities such as context acquisition, diagnosis, suggestion, and controlled execution. That is more consistent with both the actual codebase and the clarified product direction emerging from this review.

The earlier multi-agent documents remain useful because they capture an important architectural intuition: the system performs multiple distinct kinds of work, and those responsibilities should be clearly separated. But that separation does not currently require multiple independent agents with explicit handoff boundaries. In the near term, those responsibilities are better understood as internal roles, phases, or subsystems within one copilot experience.

So the practical resolution is:

the multi-agent documents should not be read as the current implementation truth,
they should be treated as conceptual design material,
and the current architecture should be documented as a single-copilot system with internally differentiated functions.

This leaves room for future evolution. If the system later reaches a point where explicit agent separation is justified, those conceptual documents may still serve as a useful foundation. But for now, the implementation target is one contextual copilot, not five independently realized agents.

---

## 2. Runtime / Planning / Approval

### Q2.1 — Every turn goes through a 12-stage pipeline even for simple questions

`run_turn()` is a ~900-line function that executes: session load → inconsistency recovery → approval reconciliation → intent detection → continuity assessment → task classification → prompt route classification → routing policy → context inventory → next-step strategy → knowledge selection → plan type inference → plan gate → plan preview → plan validation → plan registration → skills activation → system prompt composition → agent loop → finalization.

Even "qual o estado atual da cena?" goes through all of this.

**Why this matters:** This is massive overhead for simple interactions. The "smallest useful next step" philosophy would suggest many turns should skip most of this pipeline.

**Category:** Design debt
**Files:** `runtime_turn.py:121-912`

Yes — this critique is valid. A single heavy pipeline for every turn is not aligned with the intended product behavior. The current runtime appears to apply the same broad sequence of classification, planning, governance, and execution preparation to interactions that are fundamentally different in nature, including simple explanatory or diagnostic questions.

The problem is not that internal stages exist at all. The problem is that the system currently treats too many turns as if they require the same formal path. For this product, that is the wrong default. The product is converging toward a contextual technical copilot for Blender and Geometry Nodes, not a workflow engine that should wrap every turn in the same full procedure.

The intended runtime model should instead be organized around lighter turn classes, with the first question being:

“Is the current session baseline for the focused GN modifier sufficient to answer usefully?”

If the answer is yes, the agent should be able to respond directly — explaining, diagnosing, interpreting, or suggesting the next small step — without exposing a formal plan or forcing the interaction through the full governance path. In these cases, internal reasoning may still happen, and lightweight contextual reads may still be used when helpful, but the user-facing experience should remain fluid.

If the answer is no, the runtime should take the smallest useful path to restore enough context. Depending on the case, that may mean:

asking the user a clarifying question,
performing a lightweight contextual read,
or initiating a more structured baseline setup / baseline refresh for the active object, modifier, and relevant GN tree.

So the system should no longer behave as though every turn belongs to a single monolithic pipeline. Instead, turns should be routed into lighter flows such as:

clarification / conversation
diagnosis / contextual reading
baseline setup or baseline refresh
proposal
mutation

This distinction is important because proposal and mutation are not the same thing in the intended workflow. In many cases, the desired interaction is collaborative and iterative:

explain / propose → receive user feedback → refine understanding → explain / propose again

Execution should enter that loop only when explicitly requested by the user, and mutation should remain confirmation-gated.

So the resolution for Q2.1 is:

The runtime should not force every turn through the same full 12-stage governance pipeline. It should first check whether the session baseline for the focused GN modifier is sufficient, then route the turn into a lighter flow appropriate to the interaction type. The dominant interaction model should be collaborative and iterative, with heavier orchestration reserved for baseline establishment/refresh, ambiguous cases, and confirmed mutation.



### Q2.2 — The plan-first requirement blocks the LLM from acting on its own judgment

`ALWAYS_PLAN_FIRST = True` means the LLM *must* call `make_plan` before any other tool. If the LLM tries to directly call `get_node_context`, it gets a `BLOQUEADO` message. This forces a 2-round-trip minimum for any tool use (plan round + execution round), doubling latency and token cost.

**Why this matters:** The LLM's native tool-use reasoning is already a form of planning. Requiring a separate `make_plan` tool call before every action is redundant governance that adds cost and latency.

**Category:** Design debt / performance
**Files:** `execution_prechecks.py:123-153`, `agent_runtime.py:139`

Yes — this critique is valid. Requiring make_plan before any other meaningful action is too rigid for the intended product behavior. The current ALWAYS_PLAN_FIRST = True model forces unnecessary round trips, increases token cost, and introduces formal ceremony even in cases where the agent already has enough context to read, diagnose, explain, or propose the next step directly.

The intended behavior is not to make formal planning the default entrypoint for every turn. If the agent already has a sufficient session baseline for the focused GN modifier, it should be able to reason, perform lightweight contextual reads if needed, explain what it sees, and propose the next useful step without first producing a formal make_plan.

At the same time, make_plan still has value in the architecture. It should be preserved, but used selectively. In particular, it is appropriate for:

multi-step mutation
larger execution-oriented operations
riskier actions where the user should understand the intended sequence before execution
cases where the proposed implementation is complex enough that the user benefits from seeing the expected tools, steps, and execution shape in advance

In that sense, make_plan should no longer be treated as a universal gate. It should instead become a targeted execution-planning artifact: something shown to the user when a larger or riskier agent-driven execution is being prepared, and something that also functions as a technical checklist before execution begins.

For simpler interactions — especially reading, diagnosing, explaining, and proposing — the agent should be free to operate without a formal plan step. The dominant interaction loop should remain conversational and collaborative, with planning becoming explicit only when the requested action crosses into larger multi-step execution territory.

So the resolution for Q2.2 is:

make_plan should not be mandatory for all tool use or all non-conversational turns. It should be reserved for larger multi-step execution-oriented operations, where it provides real value as a user-visible planning artifact and as a technical pre-execution checklist.


### Q2.3 — Approval tokens are generated but never truly validated against a secret

Approval tokens are `appr-{uuid4().hex[:12]}`. They're stored in session state and compared against the same session state. There's no server-side secret or challenge — the runtime generates the token, stores it, and then validates against its own stored value. This is self-referential validation.

**Why this matters:** If the approval system is meant to prevent the LLM from self-approving (which it can't anyway since the user sends the approval message), the token adds complexity without security. If it's meant for MCP, the MCP client reads the token from session state and sends it back — also self-referential.

**Category:** Design debt / unnecessary complexity
**Files:** `runtime_governance.py:19-24`, `server.py:348-399`

Yes — this critique is valid. The current approval-token mechanism adds unnecessary procedural complexity without providing meaningful security guarantees in its present form. As the review notes, the token is generated by the runtime, stored in session state, and then validated against that same state, so it does not function as a true secret-based challenge.

For this product, explicit approval still matters for mutation, but the approval experience should be much simpler. The intended interaction is contextual and conversational: the agent proposes an execution-oriented action, and the user can simply say “yes, execute” or the equivalent. A visible approval token is not necessary in the normal Blender/chat experience and is more likely to create friction than clarity.

So the purpose of approval should not be tied to token exchange. Its purpose is to ensure that mutation happens only after explicit user consent. That can be achieved through normal contextual confirmation, without exposing a token or making the user participate in a technical approval ritual.

This also means pending execution state should remain lightweight. If the agent presents an execution-oriented plan and the user confirms it, execution proceeds. If the user does not confirm and the conversation moves elsewhere, that plan should not remain artificially elevated as a durable token-bound object unless there is a specific reason to preserve it. In most cases, an unconfirmed plan can simply expire as the conversation evolves.

That said, internal identifiers may still be useful for implementation details such as runtime bookkeeping, cost estimation, execution tracing, or associating an internal plan artifact with a backend operation. But those identifiers should remain internal implementation details, not part of the user-facing confirmation model.

So the resolution for Q2.3 is:

Approval should remain explicit for mutation, but it should be based on normal contextual user confirmation rather than approval tokens. The current token mechanism should not be treated as a core part of the product interaction model, and any internal identifiers that remain should be implementation details only.

### Q2.4 — Staged execution with per-stage approval is never used for more than 1 stage in practice

The stage system supports multi-stage plans with per-stage approval. But the stage generation code (`build_plan_stages` in `runtime_planning.py`) typically produces 1-3 stages, and the first stage covers the entire operation. Is there a real use case where multi-stage approval provides value?

**Why this matters:** If stages are always single-step, the entire stage tracking machinery (stage_id, stage_index, stage_status, stage_tools, stage_cursor) is dead complexity.

**Category:** Ambiguity / possible dead code
**Files:** `runtime_governance.py:53-80`, `execution_postprocess.py:117-263`

This critique is largely valid. The current staged-execution machinery appears heavier than the actual product workflow requires. While the system may support multi-stage plans in theory, the practical value does not seem to come from a formal per-stage approval/state machine with its own stage IDs, cursors, and status tracking.

The product still benefits from breaking larger execution proposals into parts. That remains useful. But the main value of those parts is not formal runtime governance — it is user comprehension and incremental collaboration. The user should be able to understand a larger execution-oriented proposal as a sequence of understandable parts, then decide whether to execute them manually, delegate them to the agent, or mix both approaches.

In practice, larger GN work should usually unfold through smaller confirmed executions across the conversation, with feedback between them. A typical pattern is not “approve a full internal stage machine and let it advance through rigid checkpoints,” but rather:

propose part A → execute or delegate → observe result → provide feedback → refine → propose part B

That pattern is better aligned with the actual collaborative workflow of this product.

So the distinction here is important:

yes, the agent may still present larger work in structured parts,
but no, that does not imply that the runtime needs a heavy formal staged-execution framework as a central mechanism.

If the implementation retains any notion of parts or phases, it should remain lightweight and user-oriented — primarily a way to structure understanding and incremental action — rather than a complex governance system that assumes most work will proceed through formal stage advancement.

So the resolution for Q2.4 is:

Larger execution-oriented proposals may still be broken into parts, but the primary value lies in user understanding and incremental collaboration, not in a heavy per-stage approval/state machine. In practice, larger GN changes should usually be carried out as smaller confirmed executions across the conversation, with user feedback between them.

### Q2.5 — The `question_only` context plan mode adds a full planning ceremony just to ask the user a question

When the system detects missing context that the user could provide, it creates a `context_plan` with `mode=question_only`. This plan has a plan_id, stages, approval tracking, presented_plan_summary, etc. — all to ask the user "which tree are you talking about?"

**Why this matters:** A conversational copilot should just ask the question directly. Creating a formal plan to ask a question is the epitome of workflow-engine behavior.

**Category:** Design debt / product mismatch
**Files:** `runtime_turn.py:679-700`, `runtime_planning.py` (infer_plan_type)

Yes — this critique is valid. A simple clarification question should not trigger the machinery of a formal context_plan with plan IDs, stages, approval metadata, and plan summaries. That behavior adds workflow-engine ceremony to what should remain part of the natural conversational loop of the copilot.

The intended behavior is that clarification should remain conversational. If the agent is missing a simple but important piece of information — for example, which GN modifier is in focus, which tree or subgroup the user is referring to, whether the user wants explanation or execution, or which region of the graph matters — it should ask directly in normal language and continue from the answer.

Those clarification turns are not failed execution attempts and should not be represented as formal plans. They are part of the normal collaborative loop of the system: understand, ask when needed, refine understanding, and continue.

At the same time, user answers to clarification questions may still be operationally important. If an answer materially defines the session focus, the baseline, or the working structure of the GN task, the system should be able to write that information back into the session workspace. For example, a clarification answer may update the active modifier in focus, the relevant tree, the current working region, or another structured part of the session baseline. That is useful state capture, but it does not require formal plan machinery.

Execution planning should remain a separate mode. It is appropriate only when the task has crossed into a larger execution-oriented operation, especially one involving multi-step mutation, higher execution risk, or a user-visible technical checklist before applying changes.

So the resolution for Q2.5 is:

Clarification should remain conversational, not plan-driven. The agent should ask directly when a simple missing detail is blocking useful reasoning, and relevant user answers may update the session workspace or baseline. Formal planning should be reserved for larger execution-oriented tasks, not for ordinary clarification.

### Q2.6 — Halt/replan logic creates infinite conversation loops

When a mutation fails, `postprocess_execution_result` sets `_halt_execution = True` and creates a replan with a new plan_id and approval_token. The LLM sees the halt message but can't act because the new plan requires approval. The user then approves, the LLM retries, and if it fails again, another replan is created. There's no circuit breaker.

**Why this matters:** A mutation that consistently fails (e.g., wrong node name) will loop through replan → approve → fail → replan indefinitely.

**Category:** Bug risk
**Files:** `execution_postprocess.py:393-423`

Yes — this critique is valid. The runtime should not enter an open-ended replan / approval / retry loop after execution failure. That behavior is too procedural, too fragile, and poorly aligned with the intended collaborative interaction model of the product.

For this system, execution failure should return the interaction to the collaborative loop, not escalate into recursive governance. If a mutation attempt fails, the default behavior should be to stop and explain, rather than automatically generating another formal plan and asking for approval again.

The intended failure policy is therefore conservative and bounded:

no automatic replan loops
after a failed execution attempt, the system should stop,
show what it tried,
show the error or failure result,
explain its hypothesis about the likely cause,
and, where useful, suggest a next alternative

This gives the user enough information to decide whether to refine the goal, provide more context, request a different proposal, or ask for another execution attempt explicitly.

A distinction between smaller local failures and larger structural failures may still be useful internally. For example, a local mismatch or stale-context issue may be easier to diagnose than a deeper structural problem in the GN logic. But even with that distinction, the runtime should not continue retrying autonomously in a loop. The product direction is not autonomous persistence at all costs; it is collaborative clarity and bounded action.

So the practical rule is simple:

after one failed execution attempt, the system should stop, explain, and hand control back to the collaborative loop.

If another execution attempt is made, it should happen as a new user-directed step, not as an automatic replan chain.

So the resolution for Q2.6 is:

Execution failure should not trigger recursive replan loops. After one failed attempt, the agent should stop, explain what it tried, surface the error and likely cause, and return control to the user-facing collaborative loop rather than continuing autonomously.


### Q2.7 — The parsimony gate can prevent the LLM from reading what it needs

`ensure_parsimony` blocks `get_tree_structure` and `get_scene_summary` if the routing policy says `session_memory_sufficient` or `structural_index_sufficient`. But the routing policy is computed *before* the LLM runs, based on regex intent detection. The LLM might discover during execution that it needs broader context, but the gate will block it.

**Why this matters:** The system's pre-computed routing decision overrides the LLM's runtime judgment, potentially causing failures or incomplete responses.

**Category:** Design debt / behavioral risk
**Files:** `execution_prechecks.py:49-77`, `runtime_turn.py:531-538`

Yes — this critique is valid. A precomputed parsimony gate should not have absolute authority to block contextual reads that the agent later discovers it genuinely needs during reasoning. In the current design, that creates the wrong kind of efficiency: it may reduce tool usage, but at the cost of incomplete understanding or brittle behavior.

Parsimony remains important in this product. Tool calls and large contextual reads are costly, and the system should avoid re-reading broad GN context unnecessarily. But parsimony should be guided by the session baseline, not enforced as a rigid pre-runtime prohibition.

The intended rule is:

the agent may seek more context if it can justify a real gap relative to the current session baseline for the focused GN modifier.

That means the runtime should favor the smallest useful path to closing the gap. In practice, the order should be:

ask the user directly if the missing detail is simple and conversationally recoverable,
use a lightweight or localized contextual read if that is sufficient,
escalate to broader structural reads only when the smaller steps cannot restore reliable understanding.

This also means that once a reliable baseline exists, smaller read tools should be easier to use. They are part of normal incremental understanding and should not be unnecessarily blocked by a coarse routing decision made before the agent has had a chance to reason about the actual gap.

Broader structural reads are different. When the agent believes a larger full-context inspection is needed, especially one known to be expensive in time or tokens, it should notify the user before escalating. Those operations should not be treated as the default reading path once a baseline already exists.

So the resolution for Q2.7 is:

The runtime should guide parsimony, not rigidly impose it. The agent should be allowed to request additional context when it can justify a real gap relative to the session baseline, using the smallest useful read first and only escalating to broader full-context inspection when necessary. Expensive broad reads should be surfaced to the user before they are performed.


### Q2.8 — `_EXECUTION_RESUME_KEYWORDS` regex is overly broad

The pattern at `agent_runtime.py:115-118` matches "ok", "okay", "pode", "sim", "vai", "bora", "segue", "seguir" as approval resume keywords. A user saying "ok, mas antes me explica o que isso faz" would be interpreted as execution resume.

**Why this matters:** False positive approval detection could trigger execution of a pending plan when the user intended a conversational follow-up.

**Category:** Bug
**Files:** `agent_runtime.py:115-118`, `runtime_turn.py:361`

Yes — this critique is valid. The current resume-keyword logic is too broad if it allows short affirmatives such as “ok,” “sim,” “segue,” or similar language to trigger execution outside a clearly defined execution-confirmation state. That creates an avoidable risk of false-positive approval, especially in a product whose normal interaction style is highly conversational and iterative.

The key issue is not just the keyword list itself. The more important issue is that approval should be state-dependent, not merely keyword-dependent.

In this product, execution should only occur after the interaction has clearly entered an execution-oriented state. That means the agent has already:

identified that execution is being requested,
presented the intended action or execution-oriented plan,
shown the relevant tools or changes it intends to apply,
and explicitly asked the user whether it should proceed

Only in that state should a short affirmative such as “yes,” “sim,” or the equivalent be treated as valid confirmation. In that context, the user’s meaning is clear enough because the execution proposal is already active and explicit.

Outside that state, short affirmatives should not trigger execution. In normal conversation, those expressions may simply mean “I understand,” “that makes sense,” “continue,” or “tell me more,” and the runtime should not reinterpret them as mutation approval.

So the correct model is:

inside an explicit execution-confirmation state → short affirmative confirmation may be sufficient
outside that state → short affirmatives must not trigger execution

This preserves a natural user experience without relying on tokens or unnatural approval rituals, while still protecting against accidental execution caused by broad keyword matching.

So the resolution for Q2.8 is:

Confirmation should be state-dependent, not keyword-dependent. A short affirmative may count as valid approval only when the system has already entered an explicit execution-confirmation state and has presented the intended tools/actions to the user. Outside that state, broad affirmative keywords should not trigger execution.


---

## 3. Session / Memory / Journal

### Q3.1 — Session state is a flat dict with 50+ keys and no schema enforcement

`session_store.py` creates a session dict with fields like `current_plan_id`, `approval_token`, `approval_status`, `current_plan_status`, `presented_plan_summary`, `presented_plan_steps`, `presented_plan_impacts`, `presented_plan_tools`, `presented_context_reads`, `presented_fallback_possible`, `presented_execute_code_risk`, `presented_plan_stages`, `current_stage_id`, `current_stage_index`, `current_stage_status`, etc. These are all string-keyed, any-typed, and scattered across 15+ files that read/write them.

**Why this matters:** Any file can write any key with any type. There's no compile-time or runtime validation. The inconsistency detection in `server.py:227-251` is a symptom of this — the system has to defensively check its own state because there's no schema.

**Category:** Technical debt
**Files:** `session_store.py`, all `runtime_*.py` files

Yes — this critique is valid. The current flat session dictionary has grown too large and too unstructured to remain a good long-term representation of session state. A session model with dozens of loosely owned top-level keys makes the runtime harder to reason about, easier to break, and more difficult to evolve safely.

The intended direction is to move away from a flat state bag and toward a structured session model organized into stable domain blocks. The session should not be modeled as an arbitrary accumulation of keys added by whichever runtime component needs them. Instead, it should be organized around the real conceptual units of the product.

For this project, the primary anchor of the session is the GN modifier in focus, with the .blend file as a secondary anchor. The most important persistent memory is not the raw chat transcript alone, but the baseline/workspace associated with the active GN task, enriched by conversation history rather than replaced by it.

So instead of a large flat dictionary, the state should evolve toward something more like:

session_identity
focus (active object / modifier / tree / subgroup)
baseline_workspace
chat_history
execution_state
ui_state
session_lifecycle / continuity

The exact schema can still evolve, but the design principle is already clear: the state should be grouped into stable domain-oriented sections with clearer meaning, clearer ownership, and clearer persistence semantics.

This also aligns with the broader product direction established in earlier decisions: the session is not merely a bag of plan-tracking metadata. It is a persistent, structured, chronological workspace centered on the GN modifier in focus.

So the resolution for Q3.1 is:

The session state should move away from a large flat dict toward a structured schema organized into stable domain blocks, with the GN modifier in focus and its baseline/workspace as the primary conceptual center of the session.


### Q3.2 — `_session_state` is mutated by reference across runtime modules with no ownership

`runtime._session_state` is passed around to `runtime_turn`, `execution_prechecks`, `execution_postprocess`, `runtime_governance`, `runtime_state_sync`, etc. Any of these can write any key at any time. There's no clear ownership of who is responsible for which keys.

**Why this matters:** When debugging why `current_plan_status` has an unexpected value, you have to search 15 files for all places that write that key.

**Category:** Technical debt
**Files:** All `runtime_*.py`, `execution_*.py`

Yes — this critique is valid. Once the session is treated as a structured workspace rather than a loose bag of flags, it no longer makes sense for arbitrary runtime components to mutate arbitrary parts of session state by reference. That pattern weakens traceability, makes debugging difficult, and undermines the stability of the session model.

The intended direction is that session state should be organized into stable domain-oriented blocks, and each block should have clearer logical ownership. That does not necessarily mean a single file must be the only code that ever touches a block, but it does mean that important state changes should happen through better-defined update paths rather than through widespread direct mutation of a shared dictionary.

For this project, that principle is especially important because the session is meant to persist as a structured workspace centered on the GN modifier in focus. Core blocks such as:

focus
baseline_workspace
chat_history
execution_state
session_identity / lifecycle

should not be treated as interchangeable flags. They represent different conceptual layers of the product and should therefore have different update responsibilities.

For example:

focus should be updated through focus-selection or focus-resolution logic,
baseline_workspace should be updated through context/baseline logic,
execution_state should be updated through execution/confirmation result handling,
chat_history should be updated through the conversation/persistence layer.

Caches, temporary views, or runtime-local copies may still exist for performance or UI purposes. But they should not become competing truths. The persisted session model should remain the authoritative state, and important blocks should have disciplined update paths.

So the resolution for Q3.2 is:

Session state should not remain a freely mutable shared dict. It should be organized into stable domain blocks with clearer logical ownership, and important state changes should occur through defined update paths rather than arbitrary direct mutation across many runtime modules.


### Q3.3 — Chat history is stored in both `_ChatSession.messages` (in-memory) and `session_store.chat_history` (on disk) with separate sync logic

`chat_ui.py` maintains `SESSION.messages` in memory. `session_store` maintains `chat_history` on disk. `_sync_ui_messages_from_session()` reconciles them. `run_turn()` appends to both independently. The `replace_messages()` method re-normalizes from disk on session_id change.

**Why this matters:** Two sources of truth for the same data with manual sync is a classic consistency bug surface. If the runtime crashes mid-turn, the disk and memory versions can diverge.

**Category:** Design debt
**Files:** `chat_ui.py:69-161, 715-729`, `runtime_turn.py:195, 910-911`

Yes — this critique is valid. The system should not maintain two competing sources of truth for conversation state, such as one chat history in UI memory and another separate chat history in persisted session storage. That duplication creates unnecessary synchronization complexity and increases the risk of divergence.

The intended direction is to keep one authoritative persisted session state, with the UI holding only a derived in-memory view or cache of that state.

At the same time, the project’s actual long-term memory model should not be centered on preserving a full raw transcript as the primary cognitive artifact. The more important persistent asset is the evolving structured understanding of the GN tree in focus — the baseline/workspace for the active session. As the conversation progresses, the user’s questions, clarifications, implemented changes, and execution results should feed that workspace and improve the system’s understanding of the tree over time.

So the goal is not “store all chat forever as the main memory.”
The goal is:

preserve one authoritative session record,
keep the GN baseline/workspace as the main structured memory,
and use a shorter recent conversation history as supporting context that helps update that baseline.

A limited recent transcript window — for example, the most recent few exchanges — may still be useful for immediate conversational continuity. But the system should not depend on maintaining two full competing histories, nor should it require the full transcript to reconstruct what the session knows. The structured understanding of the tree should be the primary persistent memory, and conversation history should support and enrich it.

So the resolution for Q3.3 is:

The system should have one authoritative persisted session state, not separate competing chat histories in UI and storage. Within that session state, the primary long-term memory should be the evolving baseline/workspace for the GN tree in focus, while a shorter recent conversation history may be retained as supporting context rather than as the main memory substrate.

### Q3.4 — Journal rotation keeps max 12 session files but there's no rotation for the index.json

`operation_journal.py` prunes old session JSONL files. But the `runtime/journal/index.json` grows without bound.

**Why this matters:** Over long-term use, the index file becomes a performance liability.

**Category:** Bug / missing feature
**Files:** `operation_journal.py`

Yes — this critique is valid. If per-session journal files are already subject to rotation or pruning, then the journal index should not be allowed to grow without bounds either. Leaving index.json unbounded creates unnecessary long-term growth in exactly the place that is meant to help organize and access journal data.

At the same time, the journal still has a legitimate role in the system. It is not the primary memory of the product — that role belongs to the structured persisted session state centered on the GN modifier in focus and its evolving baseline/workspace. But the journal remains useful as an observability and audit layer: a way to inspect how a session evolved, what actions occurred, and how the runtime behaved over time.

That means long-running sessions may still produce substantial journal records, and that is acceptable as long as it is intentional and manageable. The problem is not that journals exist or that sessions may be long. The problem is that the indexing layer should not grow indefinitely without a retention or compaction policy.

So the resolution for Q3.4 is:

The journal may continue to serve as an observability/audit mechanism for long-lived sessions, but its indexing layer should also have retention, pruning, or compaction rules. index.json should not grow without bounds even if session journals remain useful for debugging and audit purposes.


### Q3.5 — Session files are keyed by blend file path hash, but `blend_path` can be empty

When Blender hasn't saved the file yet, `bpy.data.filepath` is empty. The session is stored under an `untitled_blend_*` key. If the user saves the file and then continues, the session_id changes and all continuity is lost.

**Why this matters:** This is a realistic workflow — users often start working before saving the .blend file. Losing all session context at the first save is disruptive.

**Category:** Bug / UX issue
**Files:** `session_store.py`, `runtime_turn.py:135-153`

Yes — this critique is valid. Anchoring session identity primarily to the .blend file path is too fragile for the intended workflow, especially because beginning work before the file is first saved is a normal and expected Blender usage pattern. A session should not lose continuity simply because an untitled file is later saved under a real filename.

For this product, the primary conceptual anchor of a session is the GN modifier in focus and the structured workspace evolving around it — not the filesystem path alone. The .blend file still matters, but it should function as a secondary contextual anchor, not as the sole or primary identity of the session.

That means the correct behavior is:

an unsaved working session may begin before the .blend file has a permanent path,
the session may still build focus, baseline, and structured understanding around the active GN task,
and when the file is saved for the first time, that should update session metadata rather than create a new conceptual session.

In other words, first save should not be treated as a session reset. It should be treated as a metadata update for the same ongoing workspace.

This is especially important in the architecture now being defined, where the most valuable persisted state is the baseline/workspace for the GN modifier in focus. Losing that state because the file path changed would mean anchoring continuity to the wrong thing.

So the resolution for Q3.5 is:

Session identity should not be derived primarily from the .blend path. The GN modifier in focus and its evolving workspace should be the primary anchor, with the .blend file acting as a secondary contextual identifier. Saving an untitled file for the first time should update the same session, not create a new one.


### Q3.6 — `bump_turn_counter` is called both in `run_turn()` and in `set_modes()`

Both `runtime_turn.py:180` and `server.py:427` bump the turn counter. If MCP calls `set_modes` and the UI calls `run_turn` in the same interaction, the counter can double-increment.

**Why this matters:** Turn counter inaccuracy affects continuity assessment and journal metrics.

**Category:** Bug
**Files:** `runtime_turn.py:180`, `server.py:427`

Yes — this critique is valid. A turn counter is useful as a chronological and observability signal, but it should represent meaningful session interactions, not internal housekeeping events. If it can be incremented from multiple places for what is effectively the same user interaction, then it stops being a reliable signal.

In this product, turn count should remain secondary metadata, not a core identity mechanism. The primary continuity anchors are the GN modifier in focus, the persisted session workspace, and the evolving baseline of the active task. But a turn counter can still be useful for:

ordering session events,
journaling and observability,
comparing changes across interaction steps,
and supporting debugging or internal heuristics.

Precisely because it is a useful signal, it should be defined clearly. The correct principle is that a turn should correspond to a meaningful interaction step in the session, not to every internal technical operation performed by the runtime. Mode-setting, background synchronization, or similar housekeeping actions should not independently advance the turn count unless they are explicitly modeled as real session events.

So the runtime should have one authoritative place where turn count advances, tied to actual session-level interaction boundaries.

So the resolution for Q3.6 is:

The turn counter should represent meaningful session interactions only, not internal housekeeping events. It should remain useful secondary metadata for chronology and observability, and it should be incremented in one authoritative place only.


---

## 4. Blender UI / UX

### Q4.1 — Plan approval messages are walls of text that violate the "no Markdown tables, short sections" rule

`_render_plan_approval_message()` produces 20-30 lines of Portuguese text including plan type, plan mode, continuity check, context sources, strategy, reasoning summary, context requirements, collaboration options, summary, steps, impacts, tools, context reads, fallback possible, execute_code risk, governance notes, current stage details, and instructions. This is rendered inside a 56-character-wide Blender sidebar panel.

**Why this matters:** This is the primary user-facing output and it reads like a debug dump, not a copilot conversation. The `_request_conversational_plan_response` method attempts to convert this to natural language via an additional API call, but that costs tokens and still produces verbose output.

**Category:** UX / product mismatch
**Files:** `agent_runtime.py:688-811`

Yes — this critique is valid. The current plan/approval presentation appears too close to an internal runtime dump and too far from the intended user experience of a technical copilot. Long structured messages containing plan type, plan mode, continuity state, context inventory, strategy metadata, governance notes, stage details, and similar internals are not the right default surface for Blender-side interaction.

The intended UI direction is not to expose the runtime’s internal representation of a plan. It is to present the agent as a technical partner that communicates clearly and progressively.

That means the first layer of any plan-like or proposal-like message should be centered on:

what the agent understood
what it proposes next

not on internal plan bookkeeping.

The user-facing default should therefore be a short, clear summary first, with the possibility of seeing more detail only when that detail is genuinely useful. In many cases, the current level of “plan metadata” should disappear from the UI entirely. Much of it belongs to internal runtime state, not to the visible conversational surface.

Where additional detail is useful — especially in larger execution-oriented cases — that detail should appear only after the summary layer. For example, it may still be useful to show:

the concrete steps the agent intends to take,
the tools involved,
possible impacts,
or even rough execution/cost implications,

but only after the user has first received a clear explanation of what the agent understood and what it is proposing.

This also means presentation should vary by turn type. A diagnostic turn, a proposal turn, and a larger execution-oriented turn should not all use the same verbose format. The UI should adapt to the actual interaction rather than forcing every case into the same plan template.

So the resolution for Q4.1 is:

Plan-like UI should stop presenting internal runtime structure as if it were the final user experience. The default presentation should be layered and copilot-like: first what the agent understood and what it proposes, then only the additional execution-oriented details that are actually useful. The system should communicate as a technical partner, not as a workflow/governance dump.



### Q4.2 — The conversational plan response requires an extra API call per turn

When a plan is created, `_request_conversational_plan_response()` makes a separate Claude API call just to convert the plan snapshot into natural language. This means every plan turn costs 2x API calls — one for the pipeline, one for the conversational wrapper.

**Why this matters:** This doubles latency and token cost for every non-trivial turn. A simpler approach would be to have the main agent loop generate the conversational response directly.

**Category:** Performance / token waste
**Files:** `agent_runtime.py:864-900`, `runtime_turn.py:797-805`

Yes — this critique is valid. A second API call whose only purpose is to convert an internal plan snapshot into more conversational language is unnecessary overhead in both latency and cost. It is also a symptom of a deeper design mismatch: the system is first producing something that is not appropriate for the user-facing surface, then paying again to rephrase it.

The intended direction is that the main agent flow should generate the correct user-facing response directly. The runtime should not depend on a second LLM pass just to make plan/proposal text sound like a useful copilot message.

This does not require keeping a user-visible plan metadata layer and then rewriting it. In fact, based on the product direction now being clarified, much of that internal plan-style presentation should no longer exist as a UI artifact at all. The agent itself should already respond in the appropriate form: what it understood, what it proposes, and — when relevant — the concrete next steps.

So the correct architecture is not:

generate internal plan snapshot,
call the model again to humanize it.

It should instead be:

maintain any internal runtime state that is needed for execution or bookkeeping,
have the main agent produce the correct conversational response for the UI in the first place.

If some execution-oriented structure is still needed internally, it can remain internal. But it should not require a second model call to become presentable. And in this product direction, there is little justification for preserving that extra transformation layer as a standard part of the interaction loop.

So the resolution for Q4.2 is:

The user-facing conversational response should be generated directly by the main agent flow. The extra API call used only to rephrase internal plan output should be removed rather than preserved as a standard part of the runtime.


### Q4.3 — `_LINE_WIDTH = 56` makes the chat panel almost unusable for technical content

Node names, tool names, and error messages easily exceed 56 characters. The `textwrap.wrap` at this width fragments technical content into unreadable multi-line blocks.

**Why this matters:** The primary product surface has a fundamental readability problem for its core content type.

**Category:** UX
**Files:** `chat_ui.py:219`

Yes — this critique is valid, but the problem is broader than a single _LINE_WIDTH = 56 constant. The deeper issue is that the current text presentation model is not well adapted to the actual Blender workspace or to the kind of technical GN guidance this product needs to provide.

In practice, users may resize and reorganize the Blender workspace to make the add-on panel more usable, but the current text rendering behavior does not appear to respond well to that available space. As a result, technical content such as node names, connection guidance, structured GN instructions, or longer reasoning steps can become harder to read than they should be.

So the goal should not be framed narrowly as “just change the line width.” The more important goal is to improve technical readability inside the real Blender workspace.

That includes things such as:

better adaptation to available panel space,
less destructive wrapping of technical terms,
clearer separation between summary text and technical guidance,
and presentation formats that are more appropriate for GN-oriented explanation than plain narrow text blocks.

This is especially relevant because the product is moving toward a more technical-copilot role. It is expected to explain node logic, suggest concrete changes, and support structured GN reasoning. A UI surface that aggressively wraps everything into narrow text blocks is poorly matched to that role.

So the near-term conclusion is that the current presentation needs to be improved for readability, not merely adjusted cosmetically. And in the longer term, it may be appropriate to consider UI patterns that are more purpose-built for GN guidance rather than relying entirely on narrow wrapped chat text in a side panel.

So the resolution for Q4.3 is:

The issue is not only the fixed line width, but the mismatch between the current text-rendering model and the technical GN content the product needs to communicate. The UI should be improved around technical readability and adaptation to the actual Blender workspace, with future room for more purpose-built GN guidance surfaces if needed.


### Q4.4 — Screenshot capture is Windows-only (PowerShell + SnippingTool)

`_run_screenshot_capture()` uses PowerShell + .NET + SnippingTool.exe. This won't work on Linux or macOS Blender installations.

**Why this matters:** If the product is intended to be cross-platform, this feature silently fails on non-Windows systems.

**Category:** Missing decision
**Files:** `chat_ui.py:782-845`

Yes — this critique is valid. A screenshot-capture path that depends on Windows-specific tooling is a real limitation and should be recognized as such. If this capability remains part of the product, it should not be assumed to be universally available across environments.

At the same time, screenshot capture should not be dismissed as a trivial or purely debug-oriented feature. In this product, visual context can be genuinely useful. A screenshot may help show:

what a GN setup produced geometrically,
why the result does not match the intended outcome,
a specific region of the graph or node layout,
or a visual discrepancy that is easier to communicate through an image than through text alone.

That means screenshot capture is best understood as an important contextual aid, not as a core substrate of the copilot’s reasoning. The primary understanding model should still come from the structured session baseline, GN workspace state, and contextual reads. But screenshots can meaningfully enrich that understanding, and in some cases the agent itself may benefit from being able to request a screenshot when visual clarification would help.

So the right conclusion is balanced:

yes, the current Windows-only implementation is a portability limitation,
no, this does not need to become an immediate cross-platform priority ahead of more central product work,
but yes, if screenshot capture remains an important contextual capability, the long-term design should not rely permanently on a Windows-only path.

So the resolution for Q4.4 is:

Screenshot capture is an important visual-context aid, but its current Windows-only implementation is a real limitation. It does not need to become an immediate cross-platform priority, but it should be recognized as a non-portable stopgap rather than the final form of that capability.



### Q4.5 — The UI shows approval tokens and plan IDs in debug/advanced mode

`_get_runtime_ui_state()` exposes `approval_token`, `current_plan_id`, `execution_plan_id`, `fallback_plan_id`, etc. directly to the panel rendering. These internal identifiers are meaningless to users.

**Why this matters:** Even in debug mode, showing raw UUIDs is confusing. In normal mode, these should never be visible.

**Category:** UX
**Files:** `chat_ui.py:593-698`

Yes — this critique is valid. Raw internal identifiers such as approval_token, plan_id, execution_plan_id, or fallback_plan_id should not appear in the normal UI. They are implementation details of the runtime, not meaningful user-facing information.

This is even more true given the product direction now being clarified. The system is moving away from a heavy workflow/governance presentation model with durable pending-plan artifacts, and toward a more conversational collaborative model in which proposals are lighter, execution is explicitly requested, and confirmation is contextual rather than token-driven. In that model, exposing raw internal identifiers becomes even less justified.

If the runtime still needs internal identifiers for bookkeeping, tracing, or backend coordination, those can remain internal. But the visible UI should focus on information that helps the user operate the copilot more effectively.

So even in more advanced or debugging-oriented views, the preferred approach is not to expose raw IDs by default. It is to surface useful translated state, such as:

what object / modifier / tree is currently in focus,
whether the session baseline is established,
whether there is an execution-oriented action currently being proposed,
the last failure or warning state,
or other signals that are meaningful in terms of task progress.

If raw identifiers are ever needed for deep technical debugging, they should be treated as exceptional developer-facing details rather than standard UI content.

So the resolution for Q4.5 is:

Raw internal identifiers should not be part of the normal user-facing UI. If internal runtime state needs to be surfaced, it should be translated into meaningful task-oriented signals rather than exposed as low-level IDs.

### Q4.6 — Runtime recreates the Anthropic client on every chat turn

`_run_chat_turn()` at `chat_ui.py:863` creates a new `Anthropic()` client object on every message. This discards any connection pooling the SDK might maintain.

**Why this matters:** Minor performance issue, but also means API key changes take effect immediately (which may be intentional).

**Category:** Ambiguity
**Files:** `chat_ui.py:863`

This is a valid observation, but it is a minor issue relative to the larger architectural and UX problems identified elsewhere in the review. If the runtime currently recreates the API client on each turn, that may be somewhat inefficient, but it does not appear to be a core product concern at this stage.

For now, the simpler behavior is acceptable: recreating the client per turn may remain in place if it keeps the implementation straightforward. There is little value in over-engineering client lifecycle management while more important issues — such as interaction flow, session structure, context acquisition, and UI presentation — are still being redefined.

So the right treatment here is pragmatic: acknowledge the inefficiency, but do not elevate it into a major architectural concern. If desired, it can be cleaned up later as part of general implementation polish.

So the resolution for Q4.6 is:

This is a minor implementation issue, not a core product problem. Keeping client recreation simple for now is acceptable, and the issue can be cleaned up later without affecting the main architectural direction.


---

## 5. MCP / Integration Boundaries

### Q5.1 — There are two separate runtime implementations: `AgentRuntime` and `RuntimeBridgeCore`

`AgentRuntime` (used by chat_ui) has its own session loading, plan registration, approval tracking, knowledge selection, and system prompt composition. `RuntimeBridgeCore` (used by server.py) has its own session loading, plan rebuilding, state inference, and approval handling. These are not subclasses or composites of each other.

**Why this matters:** The product direction says "shared backend serves both surfaces without duplicating reasoning systems." But there are literally two parallel implementations of session state inference, inconsistency detection, and plan management.

**Category:** Design debt / product contradiction
**Files:** `agent_runtime.py`, `server.py:116-399`

Yes — this critique is valid. The intended architecture is a shared central runtime serving multiple surfaces, not two parallel runtime implementations that independently replicate session logic, planning logic, approval logic, and state inference.

In the current product direction, the Blender-side copilot experience is the primary surface. MCP is a secondary integration surface, useful in some circumstances, but not important enough to justify long-term duplication of the system’s core reasoning and state-management logic.

That means the current split between AgentRuntime and RuntimeBridgeCore should be treated as transitional rather than ideal. It may be acceptable as a temporary implementation state, especially while the architecture is still being reshaped, but it should not be treated as the intended steady-state design.

The correct long-term direction is:

one shared runtime model for session understanding, baseline handling, execution policy, and state transitions,
with different surfaces adapting how that shared runtime is invoked,
rather than each surface maintaining its own parallel reasoning stack.

This does not mean convergence has to happen all at once. Since MCP is secondary in the current product strategy, the convergence can happen gradually. But the design principle should be explicit now: MCP should adapt to the central runtime model, not force the project to maintain a second competing runtime architecture.

So the resolution for Q5.1 is:

The intended architecture is one shared central runtime with multiple surfaces. The current duplication between AgentRuntime and RuntimeBridgeCore should be treated as transitional and should converge over time, with MCP remaining a secondary integration surface rather than a justification for parallel core logic.



### Q5.2 — `server.py` line 192: `"conversation_surface_primary": "chatgpt"` — what?

The RuntimeBridgeCore sets the conversation surface to "chatgpt" in the session state view. This appears to be a leftover from a different project or a copy-paste error.

**Why this matters:** It's not just a naming issue — it reveals that the state_view dictionary is being copied from somewhere else without full adaptation.

**Category:** Bug
**Files:** `server.py:192`

Yes — this observation is valid. The "conversation_surface_primary": "chatgpt" value appears to be stale or residual naming and does not accurately reflect the current product architecture.

In the architecture now being clarified, the Blender-side copilot experience is the primary surface, while MCP is secondary. A label like "chatgpt" does not describe that reality clearly and is more likely to confuse than to help. It reads as leftover naming from an earlier context or an incomplete adaptation.

So this should not be defended as meaningful architectural state. It should simply be corrected or removed. If a field of this kind remains useful, it should use terminology that matches the actual product surfaces and current architecture rather than carrying forward stale naming.

So the resolution for Q5.2 is:

This is stale/residual naming and should be removed or corrected. It should not remain as-is in the runtime state model.



### Q5.3 — MCP and UI can write to the same session file simultaneously without locking

Both `AgentRuntime` (via `session.save()`) and `RuntimeBridgeCore` (via `session_store.save()`) write to the same JSON file. There's a `control_owner` concept but it's advisory by default (`control_owner_enforced` defaults to False).

**Why this matters:** Concurrent writes to the same JSON file from different threads can corrupt the session.

**Category:** Bug / race condition
**Files:** `session_store.py`, `server.py`, `chat_ui.py`

Yes — this critique is valid. Persisted session state should not be written concurrently by multiple independent runtime paths. If Blender UI and MCP can both write directly to the same session file without real coordination, that creates an unnecessary risk of state corruption, race conditions, and broken continuity.

This is especially inconsistent with the broader session model now being defined for the product: one authoritative persisted session state, structured domain ownership, and clear continuity around the GN modifier in focus.

The intended product direction is to treat the Blender-side copilot as the primary session owner. MCP is a secondary integration surface and should not be allowed to behave like a fully independent co-owner of persisted session state. If MCP remains in the architecture at all, it should operate through coordinated ownership rules rather than writing freely into the same session file as the primary UI runtime.

So the correct direction is a combination of both immediate discipline and long-term architectural convergence:

in the short term, persisted session writes should follow a single-writer or coordinated-locking discipline,
and in the longer term, this problem should naturally reduce as the architecture converges toward one shared central runtime with MCP treated as secondary.

Given the current product direction, the Blender UI path should take precedence as the main session authority.

So the resolution for Q5.3 is:

Persisted session state should not have multiple concurrent writers. The Blender-side runtime should be treated as the primary session owner, MCP should remain secondary, and session persistence should follow a single-writer or coordinated-locking model rather than allowing parallel independent writes.


### Q5.4 — The root `server.py` MCP adapter imports from `blender_connection.py` which uses `call_blender_socket`

The MCP server → `blender_connection.py` → TCP socket → `blender_addon/server.py` → handlers. This means every MCP tool call goes through 4 layers of serialization/deserialization (MCP → Python → JSON → socket → JSON → handler → socket → JSON → Python → MCP).

**Why this matters:** High latency for MCP operations. Also, if the internal socket server isn't running, MCP fails silently.

**Category:** Design debt / performance
**Files:** `server.py`, `blender_connection.py`, `blender_addon/server.py`

Yes — this critique is valid. The current MCP → connection layer → socket → add-on server chain is too heavy to be treated as desirable core architecture. It introduces unnecessary integration overhead, extra serialization layers, additional failure points, and latency for a surface that is not the primary product experience.

In the product direction now being clarified, MCP is a secondary integration surface. It should not be allowed to dictate the architecture of the main system, and this layered bridge should be understood as a transitional integration path rather than a target design.

So the correct interpretation is straightforward:

this stack may remain temporarily if needed,
but it should not be treated as the intended long-term architecture,
and its complexity should not influence the main runtime design of the Blender-side copilot.

If MCP remains in any form, it should eventually adapt to a simpler, more centralized runtime model. If MCP loses importance or is removed later, this bridge complexity should disappear with it.

So the resolution for Q5.4 is:

The current MCP-to-Blender bridge stack is transitional integration overhead, not target architecture. It is valid to keep it temporarily, but it should not shape the core design of the product and should be simplified or removed over time.



### Q5.5 — `blender_connection.py` has its own `runtime_tool_call` implementation separate from the addon's

`blender_connection.py` wraps tool calls in a `runtime_tool_call` message that goes through the TCP socket to `server.py`'s handler. The addon's own `execution_dispatch.py` calls `dispatch_tool_raw` directly. These are two different code paths for the same operation.

**Why this matters:** A safety policy change in one path might not be reflected in the other. The MCP path goes through `RuntimeBridgeCore.handle_runtime_tool_call()` with its own safety evaluation, while the UI path goes through `execution_prechecks` and then `dispatch_tool_raw`.

**Category:** Design debt / safety inconsistency risk
**Files:** `blender_connection.py`, `blender_addon/server.py`, `blender_addon/execution_dispatch.py`

Yes — this critique is valid. The system should not normalize two separate execution paths for effectively the same tool behavior, especially if those paths can diverge in safety policy, confirmation handling, or runtime semantics.

Given the product direction now being defined, tool execution should converge toward one central logical execution model. The Blender-side copilot is the primary product surface, and MCP is secondary. That means MCP should adapt to the same core execution policy rather than sustaining a parallel tool-execution path with its own quasi-independent rules.

The problem is not merely duplication of code. The more important problem is duplication of behavioral meaning. If the same tool can be reached through two different pipelines with different safety checks, confirmation semantics, or dispatch logic, then the product no longer has one coherent execution model.

So this should be treated the same way as the other MCP/runtime duplications in this section: as transitional architecture, not target architecture.

If MCP remains temporarily, it may still require an integration layer. But that layer should progressively collapse onto the same central execution policy and dispatch semantics used by the primary Blender runtime, rather than preserving a second execution interpretation.

So the resolution for Q5.5 is:

Tool execution should converge toward one shared execution model. The current existence of separate MCP and add-on execution paths should be treated as transitional duplication, not as an acceptable long-term architecture. MCP, if retained, should adapt to the same central execution semantics rather than maintaining a parallel path.


---

## 6. Knowledge / Recipes / Domain Modeling

### Q6.1 — Knowledge selection is based on keyword matching against user messages

`context_knowledge.py` defines keyword tuples like `CLINICAL_PARAMETER_KEYWORDS`, `PROXY_MODEL_KEYWORDS`, `BEZIER_RECIPE_KEYWORDS`, etc. Selection is based on substring matching against the user message and intent intents. If the user says "adjust the curve" without using any of the specific keywords, relevant knowledge won't be selected.

**Why this matters:** The knowledge system is brittle. Synonym coverage is incomplete, and there's no semantic matching.

**Category:** Design debt
**Files:** `context_knowledge.py`

Yes — this critique is valid. Knowledge selection based primarily on keyword matching against the user’s prompt is too brittle for the actual needs of this product. It cannot reliably support a copilot that is supposed to understand existing GN trees, recognize patterns that already work, reuse successful structures, and adapt domain-specific solutions to the current task.

The intended direction is that knowledge selection should be driven much more by the current GN session context than by prompt wording alone. In particular, one of the main signals for knowledge selection should be the baseline/workspace of the GN modifier in focus:

what tree is being worked on,
what structural patterns are already present,
what the current working region is,
what the current task is trying to improve or extend,
and which known patterns or recipes are already relevant to that structure.

This matters because the product is not trying to be a generic GN explainer. It is trying to become very good at the specific logic already present in the project’s own trees, and to reuse or adapt that logic where similar steps are needed again. That means project-specific recipes, examples, and working patterns should have priority over generic external knowledge whenever relevant internal material already exists.

So the intended hierarchy is:

project-internal patterns, recipes, and examples that match the active GN session,
domain knowledge that helps the agent reason about the active structure,
external/general knowledge as a supplement when internal material is insufficient.

In that model, recipes are not optional decoration. They can function as reference patterns that the agent learns to recognize, reuse, and adapt.

This also suggests a broader product direction: the knowledge layer should improve as the system is used. As more successful GN patterns, examples, and recipes are accumulated, the product should become progressively better at recognizing what already works in the project and applying that knowledge in future sessions. In other words, the knowledge system should be designed not just to retrieve static documents, but to become a stronger project-aligned pattern library over time.

So the resolution for Q6.1 is:

Keyword-only knowledge selection is too brittle. Knowledge should be selected primarily from the active GN session context — especially the baseline/workspace of the modifier in focus — with project-specific patterns, recipes, and examples treated as central reference knowledge, and with the overall product direction explicitly supporting iterative improvement of that knowledge layer over time.


### Q6.2 — `learned_patterns.md` has only one entry after the system was supposedly used multiple times

The auto-learning system (`knowledge_updater.py`) was implemented, but `learned_patterns.md` contains only a single pattern. Either the system hasn't been used much, or the extraction criteria are too strict (requires GN mutations + no errors).

**Why this matters:** If the learning system doesn't produce useful patterns in practice, it's dead weight.

**Category:** Ambiguity
**Files:** `knowledge/domain/learned_patterns.md`, `knowledge_updater.py`

Yes — this critique is valid, and it points to a real weakness in the current knowledge-learning layer. If the system has been used repeatedly but learned_patterns.md contains only a single learned entry, then the current mechanism is not delivering meaningful product value in practice.

The problem should not be minimized as “maybe the system just was not used enough.” In a product whose direction explicitly depends on becoming better at recognizing successful GN patterns, reusing what already works, and improving its project-specific knowledge over time, such a thin output strongly suggests that the current learning pipeline is too narrow, too brittle, or too restrictive to be considered a mature capability.

The direction remains correct: the product should improve its knowledge through use. But the current mechanism is too weak to carry that ambition. Learning should not depend only on a narrow automatic extraction path triggered under highly restrictive success conditions. That makes the system too passive and too unlikely to accumulate the kinds of patterns that would actually matter in this project.

A stronger learning model should be able to incorporate knowledge from multiple sources, such as:

successful recurring GN patterns,
examples that are promoted manually as references,
refined recipes,
approved working structures,
user-confirmed solutions,
and other repeated design moves that become part of the project’s evolving repertoire.

In other words, the problem is not the idea of learning. The problem is that the current implementation appears too underproductive to justify confidence in it as a meaningful capability.

So the resolution for Q6.2 is:

The current auto-learning mechanism is not delivering enough practical value and should be treated as insufficient in its present form. The product direction should still include iterative knowledge improvement through use, but that learning layer needs a broader and more effective design than the current narrowly triggered automatic extraction pipeline.



### Q6.3 — Domain knowledge files mix Portuguese and English without consistency

Some files are entirely in Portuguese (`geonodes_ortese.md`), some are in English (`canonical_anchor_system.md`), and some mix both. The system prompt is in English, the approval messages are in Portuguese, and the knowledge files are mixed.

**Why this matters:** The LLM has to context-switch languages within the same system prompt, which can degrade response quality.

**Category:** Technical debt
**Files:** All `knowledge/` files

Yes — this critique is valid, and it points to a real weakness in the current knowledge-learning layer. If the system has been used repeatedly but learned_patterns.md contains only a single learned entry, then the current mechanism is not delivering meaningful product value in practice.

The problem should not be minimized as “maybe the system just was not used enough.” In a product whose direction explicitly depends on becoming better at recognizing successful GN patterns, reusing what already works, and improving its project-specific knowledge over time, such a thin output strongly suggests that the current learning pipeline is too narrow, too brittle, or too restrictive to be considered a mature capability.

The direction remains correct: the product should improve its knowledge through use. But the current mechanism is too weak to carry that ambition. Learning should not depend only on a narrow automatic extraction path triggered under highly restrictive success conditions. That makes the system too passive and too unlikely to accumulate the kinds of patterns that would actually matter in this project.

A stronger learning model should be able to incorporate knowledge from multiple sources, such as:

successful recurring GN patterns,
examples that are promoted manually as references,
refined recipes,
approved working structures,
user-confirmed solutions,
and other repeated design moves that become part of the project’s evolving repertoire.

In other words, the problem is not the idea of learning. The problem is that the current implementation appears too underproductive to justify confidence in it as a meaningful capability.

So the resolution for Q6.2 is:

The current auto-learning mechanism is not delivering enough practical value and should be treated as insufficient in its present form. The product direction should still include iterative knowledge improvement through use, but that learning layer needs a broader and more effective design than the current narrowly triggered automatic extraction pipeline.



### Q6.4 — Recipes (`forearm_profile_anchor.md`, `shared_bezier_transition.md`) are never loaded by the runtime

Searching the codebase, `context_knowledge.py` loads from `knowledge/domain/` and some files from `knowledge/recipes/`, but only when specific keywords match. The recipe files define detailed construction protocols that the agent never sees unless the user uses the exact trigger words.

**Why this matters:** Valuable domain knowledge is unreachable unless the keyword system happens to match.

**Category:** Design debt
**Files:** `context_knowledge.py`, `knowledge/recipes/`

Yes — this critique is valid. If detailed recipes exist but are only loaded when the prompt happens to contain the right trigger words, then those recipes are being underutilized by design. That is the wrong retrieval model for a product that is supposed to recognize working GN patterns, reuse successful structures, and adapt known solutions to the current task.

In this architecture, recipes should not be treated as passive optional text. They should be treated as central reference patterns that the agent can retrieve and apply because the active GN session resembles them in structure, purpose, or working region.

That means recipe retrieval should no longer depend mainly on literal keyword matching. A recipe should become retrievable because:

the current GN baseline/workspace resembles the pattern it describes,
the active modifier or working region matches the kind of problem the recipe addresses,
the current task intent aligns with the recipe’s solution shape,
or the agent recognizes that a known project pattern is relevant to what is being built or extended.

This matters because the product direction is not just to “read documents.” It is to become increasingly good at recognizing what already works in the project and reusing that knowledge intelligently. Recipes are one of the most direct forms of that knowledge, so they should be promoted accordingly.

So the resolution for Q6.4 is:

Recipes should be treated as central reference patterns, not as passive text gated by fragile keyword triggers. The retrieval model should promote recipes based on GN session context, structural similarity, and task relevance, rather than relying primarily on prompt wording.

### Q6.5 — The `skills/` directory contains elaborate skill definitions that are only partially integrated

`skills/gn_scene_state_interpreter/` and `skills/scene_context_inspector/` each have 15+ files (schemas, examples, fixtures, scripts, notes). These are loaded by `skill_router.py` which is called by `context_skills.py`. But the actual integration is limited to two calls: `build_gn_report` and `build_scene_report`. The rest of the skill infrastructure (fixtures, examples, edge cases, tests) appears unused at runtime.

**Why this matters:** Large codebase surface area with unclear runtime utility. If these skills aren't actively used, they create maintenance burden.

**Category:** Ambiguity / possible dead code
**Files:** `skills/`, `blender_addon/skill_router.py`, `blender_addon/context_skills.py`

This critique is directionally valid, but it needs a more precise distinction between two different layers in the project.

There does appear to be a useful analytical skill layer that is at least partially integrated into the runtime — especially the scene/GN analytical skills that feed runtime-facing reports. Those capabilities should not be dismissed as dead weight if they are materially improving scene understanding or GN inspection.

At the same time, the broader surrounding skill infrastructure may be larger than the current runtime integration actually justifies. The mere existence of a large skills/ surface with supporting files, fixtures, schemas, notes, and examples should not automatically imply that all of it is equally central to the running product.

So the important architectural distinction is:

runtime-critical analytical skills that materially improve understanding of the current scene or GN state, versus
supporting skill infrastructure and development artifacts whose practical runtime role may be much smaller.

This should also be clearly distinguished from the separate knowledge/recipes corpus, which serves a different purpose. Knowledge files and recipes are part of the project’s reusable domain memory and pattern library. Skills, by contrast, are runtime-oriented analytical capabilities. Treating both surfaces as if they were the same kind of thing makes the architecture harder to reason about.

So the right direction is not to defend the entire current skill surface as equally central. It is to better integrate the parts that are genuinely useful at runtime, while being more honest about what is supporting infrastructure versus what is truly part of the product’s active reasoning layer.

So the resolution for Q6.5 is:

The useful analytical skill layer should be better integrated and clearly recognized as distinct from the knowledge/recipe corpus. But the broader skill surface should not be treated as equally central simply because it exists; the project should distinguish runtime-critical analytical capabilities from supporting infrastructure and development artifacts.


### Q6.6 — The `blender_mcp_package/` directory duplicates knowledge files

`blender_mcp_package/knowledge/domain/` and `blender_mcp_package/knowledge/recipes/` contain files that overlap with the root `knowledge/` directory. Are these separate versions? Are they synced?

**Why this matters:** Duplicate knowledge sources lead to inconsistency.

**Category:** Technical debt
**Files:** `blender_mcp_package/knowledge/`, `knowledge/`

Yes — this critique is valid. The project should not maintain multiple independent knowledge corpora as if they were equally authoritative. If both knowledge/ and blender_mcp_package/knowledge/ exist as parallel knowledge surfaces, that creates exactly the kind of drift risk the review is pointing to: duplicated maintenance, inconsistent recipes, diverging domain files, and unclear retrieval semantics.

The correct direction is to converge toward one canonical knowledge corpus. That corpus should be the single source of truth for domain knowledge, recipes, and reusable project patterns.

If blender_mcp_package/knowledge/ still exists for packaging, distribution, or transitional integration reasons, it should be treated only as a derived copy, not as an independent source of truth. It should not be manually maintained as a parallel knowledge library.

This is especially important given the product direction now being defined. Knowledge is becoming more central, not less. The system is expected to rely increasingly on reusable patterns, evolving recipes, and project-specific GN understanding. That only works if the knowledge layer converges instead of splitting.

So the resolution for Q6.6 is:

The project should converge to one canonical knowledge corpus as soon as possible. Any duplicated MCP/package-side knowledge should be treated as derived/transitional only, not as an equal knowledge source.


---

## 7. Tests / Reliability

### Q7.1 — Tests import from `blender_addon.*` but mock most of the runtime — do they test real behavior?

Most tests (`test_agent_routing.py`, `test_plan_approval_policy.py`, `test_context_knowledge.py`) create a mock runtime with minimal state and test individual functions. They don't test the full `run_turn()` pipeline, which is where most bugs manifest.

**Why this matters:** The pipeline has complex interactions between stages (e.g., parsimony gate blocking a tool the LLM needs, or approval state being in an inconsistent state after a crash). Unit tests of individual functions miss these integration issues.

**Category:** Test gap
**Files:** `tests/`

Yes — this critique is valid. The project should not treat mocked unit coverage as a sufficient signal of runtime reliability. Tests that validate isolated functions in artificial conditions still have value, but they do not adequately cover the real failure surface of this product.

In this system, the main risks do not come primarily from small helper behavior in isolation. They come from orchestration and state transitions across the full interaction flow: session continuity, baseline sufficiency, contextual reads, proposal behavior, confirmation boundaries, execution handling, and failure recovery.

That means the higher testing priority should be real interaction flows, not just local correctness of individual functions. In practice, this means the project needs more end-to-end or near-end-to-end tests that exercise the real turn lifecycle, rather than relying mainly on mocked runtime fragments as a proxy for overall reliability.

This does not make unit tests irrelevant. Unit tests still matter for local rules and small deterministic logic. But they should be understood as supporting coverage, not as the main evidence that the runtime behaves correctly as a product.

So the resolution for Q7.1 is:

Mocked unit tests are not enough to validate the reliability of this runtime. The higher priority should be end-to-end or near-end-to-end testing of real interaction flows, because the primary risk surface lies in orchestration, state transitions, and session behavior rather than isolated helper logic.


### Q7.2 — No test covers the MCP → socket → handler → response round trip

`test_mcp_server.py` mocks `_blender.runtime_tool_call()`. `test_mcp_confirmation.py` tests `resolve_user_confirmation()` in isolation. No test validates that an MCP tool call actually reaches the Blender handler and returns a correct result.

**Why this matters:** The 4-layer MCP path (Q5.4) is untested end-to-end. Silent failures in serialization, socket handling, or handler dispatch won't be caught.

**Category:** Test gap
**Files:** `tests/test_mcp_server.py`, `tests/test_mcp_confirmation.py`

Yes — this critique is valid in a narrow technical sense: there is a real coverage gap if the MCP → connection/socket → Blender handler → response path is not tested end-to-end.

However, the importance of that gap should be judged against the current product direction. MCP is no longer being treated as a primary surface. The Blender-side copilot runtime is the core product path, and MCP is a secondary or even potentially transitional integration layer.

That means the lack of full MCP round-trip testing should not be given the same priority as end-to-end reliability testing for the primary Blender runtime. If MCP remains in the system for a period of time, it is still reasonable to want minimal integration coverage for that path. But it should be understood as secondary test coverage, not as one of the main reliability priorities for the product.

So the correct conclusion is:

yes, the MCP round-trip path is currently under-tested,
but no, that should not dominate the testing roadmap,
because the architecture is intentionally shifting away from MCP as a core surface.

So the resolution for Q7.2 is:

The missing MCP end-to-end test is a real but secondary gap. If MCP remains temporarily, it may deserve minimal integration coverage, but it should not be prioritized ahead of end-to-end testing for the primary Blender-side runtime.


### Q7.3 — No test validates that session state survives a Blender restart

Session persistence is a core feature, but no test loads a session file, simulates a restart (clear in-memory state), and verifies that the session resumes correctly.

**Why this matters:** Session continuity is a key product goal. Untested session recovery means bugs in the resume path can silently lose user state.

**Category:** Test gap
**Files:** `tests/test_session_store.py`

Yes — this critique is valid, and this is an important reliability gap. Session persistence across Blender restart is not a peripheral feature in this product; it is one of the central capabilities of the session model now being defined.

The intended session behavior is that work can continue across Blender shutdown and reopen without forcing the user to rebuild context from scratch. A session may pause, but it should retain continuity through its persisted structured state — especially the GN modifier in focus, its evolving baseline/workspace, and the useful recent context needed to resume work coherently.

Because of that, it is not enough to test only isolated storage helpers or local persistence fragments. The product needs explicit test coverage for the restart-and-resume behavior itself: persist session state, clear in-memory runtime state, simulate restart, reload the session, and verify that the expected working context is still present and usable.

This should be treated as a first-class reliability scenario, not an optional edge case.

So the resolution for Q7.3 is:

The absence of a restart/resume session test is a significant gap. Since session continuity across Blender restarts is a core product capability, the project should add explicit coverage for persistence, reload, and coherent session resumption rather than relying only on lower-level session-store tests.



### Q7.4 — `test_plan_approval_policy.py` is 604 lines but doesn't test the actual `run_turn` approval path

The test creates a mock runtime, sets state values, and calls individual governance functions. It doesn't test that `run_turn()` correctly short-circuits when approval is pending, or that the approval token flows correctly from plan creation to execution.

**Why this matters:** The governance system is correct in isolation (individual functions return correct values) but may fail in the orchestration (run_turn calls them in the wrong order or with wrong state).

**Category:** Test gap
**Files:** `tests/test_plan_approval_policy.py`

Yes — this critique is valid. Testing approval-policy helpers in isolation is not enough to establish confidence in the product’s actual approval behavior. In this system, approval is not just a local rule; it is part of a larger interaction flow involving proposal, execution readiness, confirmation state, mutation boundaries, and failure handling.

That means the correctness of approval behavior cannot be inferred solely from unit tests of governance utilities. It must also be validated in the real orchestration path — especially in run_turn() or its equivalent end-to-end interaction flow.

This is even more important now that the approval model is being clarified. The project is moving away from a heavy universal governance system and toward a more specific rule set:

reading and diagnosis are fluid,
execution is only entered explicitly,
mutation requires confirmation,
confirmation is contextual and state-dependent,
and failed execution should return to the collaborative loop.

Those behaviors need flow-level tests, not just helper-level tests.

So the higher-priority testing target is not merely “does the approval helper return the right boolean,” but rather “does the runtime behave correctly across the actual proposal → confirmation → execution/failure sequence?”

So the resolution for Q7.4 is:

Approval policy should be tested as part of the real interaction flow, not only through isolated governance helpers. The project needs flow-level coverage for how approval behaves inside the actual runtime orchestration path, especially around proposal, confirmation state, execution entry, and failure return.



### Q7.5 — No test for the `knowledge_updater.py` Haiku extraction

The auto-learning system calls `claude-haiku-4-5-20251001` to synthesize patterns. There's no test that validates the extraction logic, the JSONL parsing, or the markdown append.

**Why this matters:** A broken knowledge updater would silently fail (it runs in a daemon thread with no error reporting to the user).

**Category:** Test gap
**Files:** `knowledge_updater.py`

Yes — this critique is valid. A background knowledge-update mechanism should not be treated as a meaningful product capability if it lacks both test coverage and basic reliability visibility. If the system is supposed to improve its knowledge through use, then the pipeline responsible for extracting, parsing, and persisting that learned knowledge cannot remain effectively unverified and silently failing.

This is especially important given the product direction already clarified elsewhere: iterative knowledge improvement is still a valid goal, but the current auto-learning mechanism is too weak in its present form. That makes testing and observability even more important, not less.

At minimum, the project should be able to validate that:

the update trigger path behaves as expected,
extraction/parsing does not silently corrupt output,
appending or writing learned knowledge follows the intended format,
and failure states are visible rather than silently discarded.

A background thread that may fail quietly is not an acceptable foundation for a capability that is supposed to make the agent progressively better over time.

So the resolution for Q7.5 is:

The current knowledge-update path should not remain untested and silently failing. If iterative knowledge improvement is part of the product direction, then this pipeline needs explicit test coverage and basic observability; otherwise it should not be treated as a mature learning capability.


---

## 8. Security / Safety / Dangerous Execution

### Q8.1 — `execute_code` runs arbitrary Python in Blender with no sandbox

`handlers.py:handle_execute_code()` uses `exec()` on user-provided code. `safety_policy.py` does pattern matching for `bpy.ops.wm.save`, `bpy.data.*.remove()`, `open(`, `subprocess`, `os.system`, etc. But these patterns are trivially bypassed (e.g., `getattr(os, 'system')('...')`, `__import__('subprocess')`, base64-encoded code, etc.).

**Why this matters:** While the user is also the operator (reducing the threat model), MCP exposes this to external automation. A compromised MCP client could execute arbitrary code in Blender.

**Category:** Security risk
**Files:** `handlers.py`, `safety_policy.py`

Yes — this critique is valid. Pattern-based filtering is not a real sandbox, and execute_code should not be treated as if it were a generally safe execution path simply because some risky patterns are blocked. As the review notes, that style of filtering is inherently bypassable and should not be mistaken for strong execution safety.

At the same time, execute_code should remain available in the product. It still has legitimate value as a powerful fallback capability when the existing dedicated tools are not sufficient, and it can also help expose which repeated execution intents should eventually be promoted into safer first-class tools.

So the correct direction is not to remove it, but to classify it honestly:

execute_code is a higher-risk capability
it should be explicitly controlled
it should not be the default path when a dedicated tool can accomplish the task
and its use should be visible enough that the system and the user can understand when code execution is being relied upon instead of tool-based operations

This also aligns with the broader product direction: the system should prefer specific, interpretable tools whenever possible, while retaining execute_code as a controlled fallback for exceptional or not-yet-toolized operations.

So the resolution for Q8.1 is:

execute_code should remain available, but it should be treated as a controlled high-risk fallback rather than as a generally safe execution path. The runtime should prefer dedicated tools whenever possible, and the use of execute_code should remain explicit so that the product can both control it better and learn which dedicated tools still need to be created.



### Q8.2 — MCP write restrictions default to disabled

`mcp_write_enabled` defaults to `False`, which blocks mutation tools from MCP. But `explicit_override_mode` and `debug_mode` both bypass safety checks. These can be enabled via `set_modes` from MCP itself.

**Why this matters:** A malicious MCP client could call `set_modes(explicit_override_mode=True)` and then execute anything.

**Category:** Security risk
**Files:** `safety_policy.py`, `server.py:529-534`

Yes — this critique is valid. A secondary integration surface such as MCP should not be able to relax its own write/safety restrictions by enabling override-oriented modes through the same control path it is supposed to be constrained by. That is the wrong trust model.

In the product direction now being defined, MCP is not a primary authority surface. The Blender-side runtime is primary, and MCP is secondary and potentially transitional. In that context, MCP should not be allowed to function as a self-escalating actor.

So if debug or explicit override modes continue to exist internally, they should not be exposed as routine MCP-controlled escape hatches. A surface that is already considered lower-priority and less trusted should not be the mechanism by which normal execution policy is bypassed.

This does not require overcomplicating the system. It simply means the architecture should enforce the intended hierarchy:

the primary runtime defines the normal execution policy,
MCP does not get to loosen that policy on its own,
and override-capable modes, if retained at all, should be much more tightly controlled than they are now.

So the resolution for Q8.2 is:

MCP should not be able to self-escalate into more permissive execution modes. If override/debug capabilities remain in the system, they should not be exposed as normal MCP-controlled bypass paths.


### Q8.3 — The TCP socket server has no authentication

`server.py` listens on `localhost:65432` with no authentication. Any local process can connect and send commands including `execute_code`.

**Why this matters:** On a shared machine, any process running as the same user can execute arbitrary Python in Blender.

**Category:** Security risk (low severity given localhost binding, but worth noting)
**Files:** `blender_addon/server.py`

Yes — this critique is valid. A secondary integration surface such as MCP should not be able to relax its own write/safety restrictions by enabling override-oriented modes through the same control path it is supposed to be constrained by. That is the wrong trust model.

In the product direction now being defined, MCP is not a primary authority surface. The Blender-side runtime is primary, and MCP is secondary and potentially transitional. In that context, MCP should not be allowed to function as a self-escalating actor.

So if debug or explicit override modes continue to exist internally, they should not be exposed as routine MCP-controlled escape hatches. A surface that is already considered lower-priority and less trusted should not be the mechanism by which normal execution policy is bypassed.

This does not require overcomplicating the system. It simply means the architecture should enforce the intended hierarchy:

the primary runtime defines the normal execution policy,
MCP does not get to loosen that policy on its own,
and override-capable modes, if retained at all, should be much more tightly controlled than they are now.

So the resolution for Q8.2 is:

MCP should not be able to self-escalate into more permissive execution modes. If override/debug capabilities remain in the system, they should not be exposed as normal MCP-controlled bypass paths.


---

## 9. Performance / Token Waste

### Q9.1 — System prompt includes JSON dumps of internal state on every turn

`context_prompt.py:build_system_prompt()` includes JSON-serialized `task_snapshot`, `context_snapshot`, `runtime_snapshot`, `working_memory`, knowledge snippets (up to 1400 chars each × 4), and analytical outputs (up to 1200 chars each × 4). A typical system prompt could easily be 6000-8000 tokens.

**Why this matters:** The system prompt is sent on every API call in the agent loop, including retries. High system prompt tokens multiply by the number of tool-use rounds.

**Category:** Performance / token waste
**Files:** `context_prompt.py:30-142`

### Q9.2 — The agent loop sends the full message history on every round

`agent_loop()` in `runtime_agent_loop.py` sends all messages (up to `_recent_messages(last_n=8)`) on every round of tool use. Combined with a large system prompt and multi-round tool use, a single turn can consume 50K+ input tokens across all rounds.

**Why this matters:** Token cost is a real concern for a product that makes multiple API calls per user turn.

**Category:** Performance / cost
**Files:** `runtime_agent_loop.py`, `runtime_turn.py:772`

Yes — this critique is valid. The system prompt should not behave like a catch-all dump of every available runtime snapshot, internal state structure, knowledge fragment, and analytical output on every turn. That approach is too expensive and too blunt for the product direction now being defined.

In this product, token efficiency is not just an optimization detail; it is a real design concern. The session/baseline model exists specifically so the runtime does not have to rebuild or resend the full world on every interaction.

The intended direction is that the prompt should be built around:

the active GN session baseline/workspace,
a small amount of recent conversational context,
and only the minimum additional knowledge or contextual data needed for the current turn.

That means the runtime should stop treating large serialized state dumps as the default solution for uncertainty. If a broader context is genuinely needed, it should be requested incrementally and selectively, not eagerly injected into every system prompt.

This is also aligned with the broader interaction model already clarified elsewhere: the agent should rely on persistent session understanding, lightweight contextual reads, and structured knowledge selection, rather than compensating for architectural uncertainty by repeatedly sending oversized prompt payloads.

So the resolution for Q9.1 is:

The system prompt should stop functioning as a broad state dump. It should be centered on the active session baseline/workspace, recent useful conversational context, and only the minimum additional context required for the current turn.

Yes — this critique is valid. Sending the full recent message history on every tool-use round is too expensive for a product that is supposed to rely on persistent session understanding rather than repeated conversational replay.

The intended architecture already points to a better model: the main persistent memory should be the GN session baseline/workspace, not a repeatedly replayed transcript. A short recent conversational window may still be useful for local continuity, but it should remain supporting context, not the primary substrate of reasoning.

This means the runtime should minimize repeated history payloads and rely more on:

the persisted structured session state,
the active GN baseline/workspace,
and only the minimal recent conversational context needed for the current turn.

So the resolution for Q9.2 is:

The runtime should stop depending on repeated full-history transmission as a default. It should rely primarily on the persisted GN session baseline/workspace, using only a small recent conversational window when needed for local continuity.


### Q9.3 — Knowledge selection loads and truncates files on every turn

`load_knowledge_snippet()` reads files from disk and truncates at `max_chars` on every turn. There's no caching between turns.

**Why this matters:** Minor disk I/O issue, but the real cost is that selected knowledge is re-evaluated from scratch every turn instead of persisting relevant knowledge in the session.

**Category:** Minor performance
**Files:** `context_knowledge.py`

Yes — this critique is valid. The issue is not only repeated file reads from disk, but the broader pattern of re-evaluating knowledge from scratch on every turn instead of treating relevant knowledge as part of the evolving session context.

In the product direction now being defined, knowledge should be selected primarily from the active GN baseline/workspace and task context. That means once certain patterns, recipes, or domain references become relevant to the focused session, the runtime should not have to rediscover them from zero on every round.

A better model is:

select relevant knowledge from session context,
persist that relevance in the workspace where appropriate,
and only refresh or expand knowledge selection when the task or structural context materially changes.

So the resolution for Q9.3 is:

Knowledge selection should become more session-aware and less turn-by-turn repetitive. Relevant knowledge should not be reloaded and re-truncated from scratch on every round if the session baseline already establishes its relevance.

### Q9.4 — The extra API call for conversational plan responses doubles the cost of plan turns

As noted in Q4.2, `_request_conversational_plan_response()` makes a separate API call. For a plan turn, the total cost is: (1) the main pipeline classification + plan generation, (2) the conversational wrapper API call. Neither produces tool execution.

**Why this matters:** Two API calls that produce zero Blender-side work is poor value.

**Category:** Performance / token waste
**Files:** `agent_runtime.py:864-900`

Yes — this critique is valid. If a plan turn requires one model call to build internal structure and then a second model call just to convert that structure into user-facing conversational language, the system is paying twice for a problem it should solve once.

The product direction already clarified elsewhere makes the correct fix straightforward: the main agent flow should produce the right user-facing response directly. The runtime should not depend on a second model pass just to “humanize” internal plan output.

This is not just a cost issue. It is also a design issue. A second conversationalization call only exists because the system is first generating something that is too runtime-shaped to be shown to the user.

So the resolution for Q9.4 is:

The extra model call used only to conversationalize internal plan output should be removed. The main agent flow should generate the correct user-facing response directly, eliminating that duplicated cost.


---

## 10. Naming / Clarity / Maintainability

### Q10.1 — `runtime_dispatch.py` and `execution_dispatch.py` have confusingly similar names

`runtime_dispatch.py` is the `RuntimeDispatcher` class that handles tool execution inside Blender (creating nodes, reading trees, etc.). `execution_dispatch.py` is a thin wrapper that calls `dispatch_tool_raw` and formats the result. The names don't clearly convey what each one does.

**Why this matters:** A developer looking for "where tools get dispatched" will find two files and not know which one to look at.

**Category:** Naming
**Files:** `blender_addon/runtime_dispatch.py`, `blender_addon/execution_dispatch.py`

Yes — this critique is valid. File names should make architectural responsibility easier to understand, not harder. Having runtime_dispatch.py and execution_dispatch.py side by side, both apparently related to dispatch behavior, creates unnecessary cognitive friction for anyone trying to navigate the codebase.

The deeper problem is not just superficial naming similarity. It is that the current file names do not clearly communicate the difference between:

the core runtime execution/dispatch model,
and any thinner wrapper or adapter layer built around it.

As the project moves toward a clearer shared-runtime architecture, naming should become more explicit and responsibility-oriented. Files should be named according to what role they actually play in the execution model, not merely according to implementation history.

So the resolution for Q10.1 is:

The current naming is unnecessarily confusing and should be cleaned up. File names should be revised so that the central execution/dispatch path and any wrapper/adapter layers are clearly distinguishable by responsibility rather than by subtle naming differences.


### Q10.2 — `AgentRuntime` is a massive wrapper class that delegates everything

`AgentRuntime` has 40+ methods, almost all of which are 1-3 line wrappers that call functions from other modules. The class holds state (`_session_state`, `_routing_policy`, `_plan_gate`, etc.) and passes `self` to module-level functions as `runtime: Any`. This is the "god object" pattern.

**Why this matters:** The `Any` type annotation on `runtime` means there's no type safety. Any module can access any attribute on the runtime, and there's no way to know what a module depends on without reading it.

**Category:** Design debt
**Files:** `agent_runtime.py:169-900`

Yes — this critique is valid. AgentRuntime currently appears to function too much like a god object: it holds broad cross-cutting state, exposes many thin wrapper methods, and serves as the implicit dependency surface for many other modules. That makes the architecture harder to reason about, harder to type safely, and harder to evolve cleanly.

The project’s direction now points toward a different model:

a smaller central runtime concept,
a structured session model,
clearer domain blocks,
and better-defined ownership of operations such as focus resolution, baseline management, execution state, and UI/session interaction.

In that architecture, the runtime should still exist as a coordinating center, but it should not remain an unbounded object that all modules depend on through broad Any-style access. The runtime should become thinner, with clearer internal services or domain-oriented components responsible for specific parts of behavior.

So the resolution for Q10.2 is:

AgentRuntime should stop acting as a broad god object. The runtime should be thinned into a clearer coordinating layer, with more explicit domain responsibilities and narrower interfaces instead of widespread wrapper-based access to a shared object.


### Q10.3 — Portuguese and English are mixed throughout the codebase

System prompt: English. Approval messages: Portuguese. Block messages: Portuguese. Comments: mostly English. Knowledge files: mixed. Variable names: English. User-facing text: Portuguese. Journal event types: English.

**Why this matters:** Inconsistency makes the code harder to maintain and understand.

**Category:** Technical debt
**Files:** Throughout

Yes — this critique is valid. Mixed-language codebases create avoidable maintenance friction, especially in a project that already depends heavily on structured knowledge retrieval, runtime reasoning, and architectural clarity. The project should not continue treating language inconsistency as neutral technical background noise.

This is especially important because earlier decisions already established a clear direction for the knowledge layer: English should be the canonical language. That same principle should now be extended more broadly across the maintainable project surface.

That does not necessarily require rewriting every legacy artifact immediately. But the direction should be explicit:

new architectural docs should be in English,
new runtime-facing code comments and developer-facing operational documentation should be in English,
new names and structural abstractions should follow a consistent English vocabulary,
and mixed-language drift should be treated as technical debt to be reduced over time.

So the resolution for Q10.3 is:

The codebase should converge toward English as its canonical maintainability language. Mixed Portuguese/English usage should be treated as technical debt and reduced progressively rather than accepted as a stable norm.


### Q10.4 — The `contracts/` directory defines schemas that aren't validated anywhere

`contracts/journal_event.schema.json`, `contracts/runtime_tool_call.schema.json`, `contracts/tool_inputs.schema.json` exist but no code loads or validates against them.

**Why this matters:** Schemas without validation are dead documentation that will drift from reality.

**Category:** Dead code
**Files:** `contracts/`

Yes — this critique is valid. Schemas and contracts that are not actually used to validate runtime behavior should not be treated as reliable governance artifacts. In that state, they are closer to dead or drifting documentation than to active architectural guarantees.

This matters because the broader direction of the project is toward clearer structure, not toward a larger collection of nominal formalisms that the runtime silently ignores. If a schema exists, it should have one of two statuses:

either it is active and participates in validation, testing, or runtime discipline,
or it is inactive/reference-only and should not pretend to govern the system.

The current in-between state is the worst of both worlds.

So the resolution for Q10.4 is:

Contracts and schemas should either become real validated artifacts or be demoted/removed as non-governing documentation. The project should not keep formal-looking schemas that are not actually enforced anywhere.


### Q10.5 — `runtime_planning.py` at 1574 lines is the new monolith

This file contains intent detection, task classification, continuity assessment, context source inventory, next-step strategy, plan type inference, plan preview building, plan stage building, routing policy, plan gate, tool derivation, and various helper functions. It's the conceptual core of the agent's reasoning, all in one file.

**Why this matters:** Same problem as the original monolithic `agent_runtime.py`, just moved to a different file.

**Category:** Technical debt
**Files:** `blender_addon/runtime_planning.py`

Yes — this critique is valid. Even if the old monolith was physically split across files, the architectural problem has not been solved if one file still concentrates too much of the system’s conceptual reasoning in one place. A very large runtime_planning.py strongly suggests that the product’s decision logic is still too entangled.

This is especially important because earlier decisions in this review have already simplified the intended interaction model:

not every turn should go through the same heavy pipeline,
baseline sufficiency should be a first-class routing decision,
clarification should remain conversational,
planning should be selective,
and execution should be entered explicitly.

That means the future design should not preserve one giant planning brain that tries to own all possible turn classes under one file. The planning logic should instead be reduced and separated according to the lighter architectural model now being defined.

The key goal is not merely file splitting for its own sake. It is model simplification: fewer universal pathways, fewer pseudo-governance layers, and clearer distinctions between clarification, diagnosis, baseline setup/refresh, proposal, and execution.

So the resolution for Q10.5 is:

runtime_planning.py should be treated as the new conceptual monolith and should be reduced accordingly. The next refactor should focus on simplifying the underlying interaction model and separating planning responsibilities along the lighter turn classes now being defined, rather than merely redistributing code mechanically.


---

## 11. Technical Debt / Refactor Strategy

### Q11.1 — The refactoring split code across files but didn't simplify the conceptual model

The original `agent_runtime.py` was split into ~15 files. But the overall flow — intent → classify → continuity → routing → inventory → strategy → plan type → plan gate → preview → validate → register → skills → prompt → loop → finalize — is unchanged. The complexity was distributed, not reduced.

**Why this matters:** The refactor plan (`docs/refactor_plan_ui_copilot.md`) recommends "Cognitive Loop Simplification" as the highest-value next step. The file split didn't achieve this.

**Category:** Design debt
**Files:** All `runtime_*.py`, `execution_*.py`, `context_*.py`

Yes — this critique is valid. Splitting a large file into many smaller files is not enough if the product still behaves according to the same heavy conceptual model. In that case, the refactor improves physical organization but does not reduce the cognitive burden of understanding or evolving the system.

That is exactly the issue here. Earlier decisions in this review have already clarified that the main problem is not simply file size. The main problem is that too much of the system still assumes a universal pipeline of classification, planning, governance, and execution handling, even for interactions that should be lightweight and collaborative.

So the next refactor should not be judged primarily by how many files it creates. It should be judged by whether it actually simplifies the product model:

fewer universal pathways,
clearer turn classes,
less ceremony,
less duplicated reasoning,
and a stronger baseline/session-centered design.

So the resolution for Q11.1 is:

The review is correct: file splitting alone did not solve the deeper problem. The next refactor must reduce the conceptual model itself, not just redistribute its code across more modules.

### Q11.2 — Should read-only operations bypass the plan/approval system entirely?

Read tools (`get_node_context`, `get_scene_summary`, `get_tree_structure`, `capture_screenshot`) are already classified as `auto_apply` in `safety_policy.py`. But the governance system still requires a plan before reads. Should reads be allowed to execute directly in the agent loop without plan/approval ceremony?

**Why this matters:** This is probably the single highest-impact simplification for copilot feel.

**Category:** Missing decision
**Files:** `safety_policy.py`, `execution_prechecks.py`

Yes — read-only and diagnostic operations should bypass the heavy plan/approval system by default. This is one of the clearest architectural decisions established in this review.

The product is not meant to behave like a workflow engine for every turn. It is meant to behave like a contextual technical copilot. That means reading, diagnosing, explaining, and lightweight contextual inspection should remain fluid and should not require formal planning or approval ceremony.

This does not mean those operations happen without structure. They should still be grounded in the session baseline/workspace for the GN modifier in focus, and they may still use lightweight contextual reads as needed. But they should not be forced through the same plan-first or approval-first machinery intended for mutation.

Mutation is different. Mutation remains confirmation-gated. But read-only work should not be artificially wrapped in execution-oriented governance.

So the resolution for Q11.2 is:

Yes — read-only and diagnostic operations should bypass the plan/approval pipeline by default. They should be handled through the lighter baseline-driven interaction model, while mutation remains separately confirmation-gated.


### Q11.3 — Should the `make_plan` tool be removed in favor of the LLM's native reasoning?

The `make_plan` tool forces the LLM to output a structured plan before acting. But the LLM already reasons about its next step in the tool-use response. The `make_plan` output is then re-processed by the runtime into a formal plan with stages. If the LLM's native reasoning is trusted, `make_plan` is redundant.

**Why this matters:** Removing `make_plan` would cut 1 tool-use round per turn, reduce token cost, and simplify the entire governance pipeline.

**Category:** Missing decision
**Files:** `tools.py`, `execution_prechecks.py:261-316`


Partially. The current universal make_plan requirement should be removed, but the concept of explicit planning should not disappear entirely.

Earlier decisions already established the correct middle ground:

make_plan should not be mandatory for all tool use or all non-conversational turns,
but explicit planning still has value for larger multi-step execution-oriented operations,
especially when the user benefits from understanding the intended steps, tools, and impacts before execution.

So the right conclusion is not “keep universal plan-first” and not “abolish all planning.” It is:

eliminate make_plan as a universal entry gate,
preserve explicit planning as a selective capability for larger execution-oriented work.

That aligns with the product’s collaborative model: explain and propose by default, then use formal planning only when the requested change is large enough, risky enough, or execution-heavy enough to justify a visible checklist.

So the resolution for Q11.3 is:

The universal plan-first requirement should be removed. Explicit planning should remain available, but only as a selective execution-planning artifact for larger multi-step operations rather than as a mandatory step before ordinary reasoning or tool use.


### Q11.4 — The `snapshots/` directory contains full codebase copies from previous states

`snapshots/current_20260401_213329/` and `snapshots/restore_from_blend_IA_ort_zip_20260401_012524/` contain complete copies of the codebase at previous points in time. These are 100+ files each.

**Why this matters:** This is what git is for. Keeping full codebase snapshots in the repo is wasteful and confusing (which version is the real one?).

**Category:** Technical debt
**Files:** `snapshots/`

Yes — this is technical debt and should be cleaned up. Keeping large full-codebase snapshots inside the repository is not a good long-term maintenance pattern, especially in a project that is already struggling with conceptual and structural bloat.

A repo should not treat full copied codebase states as normal architecture support unless there is a very explicit and justified archival process behind them. In most cases, this kind of directory becomes confusion surface:

which copy is current,
which copy is reference,
which copy is safe to ignore,
and whether stale implementations are still influencing the active system.

Given the current cleanup/refactor direction, these snapshot directories should not be preserved as normal project structure.

So the resolution for Q11.4 is:

The snapshots/ directory should be treated as technical debt and removed from the normal project architecture. Full repository-state copies should not remain as active in-repo structure unless there is a very explicit archival reason.



### Q11.5 — Is the `blender_mcp_package/` directory actively used or a remnant?

`blender_mcp_package/` contains its own `knowledge/`, `recipes/`, and `tools/` directories. It's not imported by the main codebase. Is this a distributable package, a development artifact, or dead code?

**Why this matters:** If it's dead, it should be removed. If it's a distributable package, it needs its own README explaining how it relates to the main project.

**Category:** Ambiguity
**Files:** `blender_mcp_package/`

The review is correct to flag this as ambiguity, and the project should not leave it ambiguous any longer. The current direction of the product makes one thing clear: blender_mcp_package/ should not remain an undefined parallel surface.

Earlier decisions already established that:

MCP is secondary,
may be transitional,
and should not drive the core architecture.

So the project should force a clean decision here:

either blender_mcp_package/ has a real, explicit packaging/distribution role,
or it should be treated as transitional residue and removed.

What should not continue is the current in-between state where it duplicates knowledge surfaces or suggests a parallel architecture without a clearly maintained product role.

So the resolution for Q11.5 is:

blender_mcp_package/ should no longer remain architecturally ambiguous. It must either be explicitly defined as a derived packaging/distribution artifact or be removed as transitional residue. It should not continue as an unclear parallel project surface.



### Q11.6 — `reference/` contains code from the old project but is not used at runtime

Files like `reference/exec.py`, `reference/generator_base.py`, `reference/investigator.py`, etc. are from the old project referenced in CLAUDE.md. They're present in the repo but not imported anywhere.

**Why this matters:** Dead code creates confusion about what's active.

**Category:** Dead code
**Files:** `reference/`

Yes — this should be treated as dead or archival material, not as part of the active architecture. If code in reference/ is not imported, not part of the runtime, and not governing current behavior, then keeping it in the active repository structure without clear framing only adds confusion.

That does not necessarily mean every such file must be deleted immediately. But it does mean the project should stop allowing old reference code to sit in a gray zone between “active” and “archival.”

Given the broader cleanup direction now being established, the healthier rule is:

active code should be clearly active,
archival/reference material should be clearly archival,
and dead code should not remain mixed into the navigable project surface as if it still matters.

So the resolution for Q11.6 is:

The reference/ directory should not remain in an ambiguous active-looking state. It should either be clearly archived/documented as reference-only or removed from the normal active project surface.


---

## 12. Specific Behavioral Questions

### Q12.1 — What happens when the user sends a message while the agent is still processing?

`SESSION.running` is checked in `_send_user_message()`, but the check happens in the UI thread while the processing happens in a daemon thread. Is there a race condition between checking `running` and setting it?

**Why this matters:** Double-submission could cause two concurrent turns writing to the same session.

**Category:** Bug risk
**Files:** `chat_ui.py:938-939`

Yes — this is a real risk and should be treated as such. In a product centered on persistent session state and collaborative continuity, concurrent overlapping turns are not harmless UI noise; they are a potential source of session corruption, duplicated writes, and broken chronology.

The correct product behavior should be that one session turn is processed at a time. A new message should not start a second competing turn against the same live session state while the previous one is still running.

This aligns with several earlier decisions:

the session should have one authoritative persisted state,
the Blender-side runtime should be the primary session owner,
session chronology should remain meaningful,
and turn count should represent real interaction steps, not overlapping races.

So the resolution for Q12.1 is:

The system should treat overlapping user submissions during an active turn as a real concurrency risk. A session should process one turn at a time, and new user input should not begin a competing concurrent turn against the same live session state.


### Q12.2 — What happens when `knowledge_updater` runs `claude-haiku` and the API key is invalid?

`maybe_extract_knowledge()` runs in a daemon thread. If the API call fails, the error is caught and silently discarded. The user has no visibility into whether learning is working.

**Why this matters:** Silent failure in a background system means it could be broken for weeks without anyone noticing.

**Category:** Missing observability
**Files:** `knowledge_updater.py`

Yes — this is a valid observability problem. A background learning/update mechanism should not fail silently if the product intends to treat iterative knowledge improvement as a meaningful capability. Silent failure makes the feature impossible to trust and too easy to ignore for long periods.

This connects directly to the earlier conclusion in Q6.2 and Q7.5: the current learning pipeline is already too weak to be treated as a mature capability, and silent background failure makes that even worse.

The right behavior is not necessarily to interrupt the user with noisy alerts, but the system should at least surface actionable visibility somewhere appropriate, such as:

a runtime warning,
a visible debug/health signal,
a journal entry,
or a clear status that learning/update is unavailable.

So the resolution for Q12.2 is:

Background knowledge-update failures should not remain silent. If iterative knowledge improvement is part of the product direction, invalid credentials or similar failures need at least basic observability rather than being discarded invisibly.



### Q12.3 — The `structural_index` can grow without bounds

Every `get_tree_structure` call adds to `_structural_index` via `runtime_state_sync.py`. There's no eviction policy. Over many sessions, this dict can grow to include every tree the agent has ever read.

**Why this matters:** The structural index is included in the system prompt's working memory section and serialized to the session file.

**Category:** Performance / bug
**Files:** `runtime_state_sync.py`, `session_store.py`

Yes — this critique is valid. Any structure that accumulates context across time and is reused in prompts or persisted session state needs bounded growth rules. An unbounded structural_index is especially problematic in this product because prompt size and session clarity are already major concerns.

This is directly related to the broader architecture already defined:

the session should revolve around the focused GN modifier,
the baseline/workspace should be the main structured memory,
and the system should load context incrementally rather than retaining every structural artifact forever.

So the structural_index should not grow indefinitely as a passive catch-all store. It should be governed by session relevance, focus, and retention rules. The runtime should keep what is useful to the active session and discard or compress what is no longer relevant.

So the resolution for Q12.3 is:

The structural index should not grow without bounds. It should be governed by relevance to the active GN session and bounded by retention/compaction rules so it does not become another uncontrolled memory surface.


### Q12.4 — Context plan completion auto-creates an execution plan, but the user hasn't asked for execution yet

`advance_stage_after_success()` at `execution_postprocess.py:221-262`: when all context stages complete and there's a `pending_original_goal`, the system automatically creates an execution plan and asks for approval. But the user's original request might have been a question, not an execution request.

**Why this matters:** The system assumes that context gathering is always a precursor to execution. Sometimes the user just wants to understand the current state.

**Category:** Design debt / UX
**Files:** `execution_postprocess.py:221-262`

Yes — this critique is valid. Automatically escalating from context acquisition into execution planning is not consistent with the product direction established in this review. Understanding and execution are not the same thing, and the system should not assume that gathering context automatically implies that the user wants mutation next.

This is especially important because the intended interaction model is explicitly collaborative:

understand the tree,
explain,
propose,
receive feedback,
and only enter execution when the user actually wants that.

So context completion should not auto-promote itself into an execution-oriented state. The product should preserve the distinction between:

context/understanding
proposal
execution

If the user wants execution after understanding, that should be entered explicitly, not inferred automatically as the default next step.

So the resolution for Q12.4 is:

Context completion should not automatically create an execution plan. The system should preserve a clear boundary between understanding, proposal, and execution, and should enter execution-oriented planning only when the user actually requests or accepts that transition.


---

## Decision Priorities

Based on this review, here are the decisions that will have the highest impact on the product direction:

1. **Q1.1 + Q2.1 + Q11.2**: Should read-only and diagnostic turns bypass the plan/approval pipeline?
2. **Q1.2**: What is the actual intended approval policy? CLAUDE.md vs. code.
3. **Q2.2 + Q11.3**: Should `make_plan` be removed or made optional?
4. **Q5.1**: How to unify `AgentRuntime` and `RuntimeBridgeCore`?
5. **Q4.1 + Q4.2**: How to make plan responses conversational without extra API calls?
6. **Q1.3 + Q1.4**: CLAUDE.md needs a complete rewrite to match reality.
7. **Q3.1 + Q3.2**: Session state needs a schema and ownership model.
8. **Q2.8**: The approval detection regex needs tightening.

Answer these and we can begin implementation.

Decision Priorities — Consolidated Direction

The highest-impact decisions from this review now have a coherent answer.

First, read-only and diagnostic turns should bypass the heavy plan/approval pipeline by default. The product direction is not a workflow engine that formalizes every non-conversational interaction. It is a contextual technical copilot for Blender and Geometry Nodes. That means the runtime should first ask whether the current session baseline for the focused GN modifier is sufficient. If it is, the agent should be able to inspect, diagnose, explain, and suggest the next useful step without entering formal planning or approval machinery. Heavier orchestration should be reserved for baseline establishment or refresh, ambiguous cases, and confirmed mutation.

Second, the approval policy is now explicit. For Geometry Nodes, read-only inspection and diagnosis should be autonomous, but mutations should always require explicit user confirmation. This resolves the contradiction between the old wording in CLAUDE.md and the current runtime behavior. The code is directionally correct to require confirmation for mutation. What was wrong was the overly broad documentation language implying that GN operations in general should happen without confirmation. The correct distinction is between understanding-oriented actions and change-oriented actions.

Third, make_plan should no longer be a universal gate. It should not be required before normal reading, diagnosing, explaining, or proposing. However, it should not be removed entirely either. Explicit planning still has value for larger multi-step execution-oriented operations, especially when the user benefits from seeing the intended steps, tools, and impacts before execution. In other words, make_plan should become selective and situational, not mandatory by default.

Fourth, the architecture should converge toward one shared central runtime, not two parallel reasoning systems. The Blender-side copilot is the primary product surface. MCP is secondary, and possibly transitional. That means AgentRuntime and RuntimeBridgeCore should not remain independent long-term centers of duplicated logic. The target architecture is one shared runtime model for session state, baseline handling, execution policy, and interaction flow, with different surfaces adapting to it rather than re-implementing it.

Fifth, plan responses should become conversational in the main flow itself, not through a second API pass. The current extra call used to convert internal plan output into user-facing language is both expensive and architecturally revealing: it means the system is first generating the wrong shape of output and then paying again to correct it. The correct direction is for the main agent flow to produce the right user-facing response directly — first what the agent understood, then what it proposes, and only then any execution-oriented detail that is genuinely useful.

Sixth, CLAUDE.md needs a full rewrite. It should become a short operational entrypoint for Claude Code / Codex, not a stale hybrid of old architecture, current behavior, and future aspiration. It should clearly separate current reality from target direction, reflect the actual architecture that exists today, and act as a portal to deeper documentation rather than pretending to be the full source of truth by itself. Stale instructions such as “do not recreate” rules that no longer match reality should be removed or rewritten.

Seventh, session state needs a structured schema and clearer ownership model. The current flat session dictionary should evolve into stable domain blocks centered on the actual product model: the GN modifier in focus, the baseline/workspace of that active session, structured execution state, recent useful chat context, and session lifecycle metadata. Session state should not remain a freely mutated shared bag of keys. It should become a structured persisted workspace with clearer logical ownership and defined update paths.

Finally, approval detection must become state-dependent rather than keyword-dependent. Short affirmatives such as “yes” or “sim” can be valid, but only when the system has already entered an explicit execution-confirmation state and has presented the intended tools or changes. Outside that state, broad affirmative keywords must not trigger execution. This protects the collaborative conversational loop while preserving natural confirmation behavior when execution is actually pending.

Taken together, these decisions define the new product direction clearly: a baseline-driven, session-persistent, collaborative GN copilot that explains and proposes by default, executes only when explicitly requested and confirmed, and stops wasting architecture on universal ceremony, duplicated runtimes, stale docs, and bloated prompt/state handling.