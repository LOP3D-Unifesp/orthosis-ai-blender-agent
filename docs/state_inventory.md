# State Inventory

Este inventario lista onde o addon guarda estado hoje, quem escreve, quem le,
e quais campos sao fontes de bugs por duplicacao ou ambiguidade.

## 1. Fontes de estado duravel

### Session V1 JSON

Local: `runtime/sessions_v1/*.json`.

Codigo:

- Schema: `blender_addon/session/schema.py:875`.
- Store: `blender_addon/session/store.py:73`.
- Load por blend file: `blender_addon/session/store.py:120`.
- Save: `blender_addon/session/store.py:368`.
- Exposto pelo runtime: `Runtime.v1_session_for()` em `blender_addon/runtime/core.py:195`.

Conteudo principal:

- `identity`: id, schema, timestamps.
- `focus`: blend path, object, modifier, tree.
- `baseline_workspace`: baseline semantica/estrutural.
- `history`: historico espelhado, mas nao deve ser fonte principal da UI.
- `execution_state`: draft, falhas, pending decision, session state, work cycle.
- `ui_state`: flags debug/override/MCP/simulate.
- `operational_state`: memoria de ferramentas e arvore.
- `lifecycle`: continuidade e notas.

Status: ativo e deve ser preservado.

### ChatHistoryStore JSONL

Local: `runtime/chat_history/<session_id>.jsonl`.

Codigo:

- `ChatHistoryStore` em `blender_addon/session/chat_store.py:26`.
- Append com fsync em `blender_addon/session/chat_store.py:40`.
- Runtime append em `blender_addon/runtime/core.py:236`.
- AgentRuntime grava user/assistant antes do save V1 em `blender_addon/agent_runtime.py:718`.

Status: ativo, bom design. E a fonte mais confiavel da conversa visivel.

### SessionStateStore

Local: `runtime/session_state/<session_id>.json`.

Codigo:

- Store: `blender_addon/session/session_state_store.py:34`.
- Transicao derivada: `compute_next_state()` em `blender_addon/session/session_state_store.py:130`.
- Runtime read/write: `blender_addon/runtime/core.py:270` e `blender_addon/runtime/core.py:276`.
- AgentRuntime hidrata no inicio do turno em `blender_addon/agent_runtime.py:300`.

Campos:

- `session_state`
- `previous_state`
- `blend_path`
- `updated_at`

Status: ativo. Bom para o repair loop, mas duplica `ExecutionState.session_state`.

### OperationJournal

Local: `runtime/journal/`.

Codigo:

- `OperationJournal` em `blender_addon/operation_journal.py:199`.
- `start_run()` em `blender_addon/operation_journal.py:293`.
- `start_goal()` em `blender_addon/operation_journal.py:520`.
- `log_tool_call()` em `blender_addon/operation_journal.py:854`.
- `log_runtime_event()` em `blender_addon/operation_journal.py:902`.

Status: ativo e indispensavel para debug de sessoes reais.

### Draft no Blender Text Editor

Local: `bpy.data.texts["GN_Agent_Draft"]`.

Codigo:

- Write: `handle_write_script_draft()` em `blender_addon/handlers.py:1503`.
- Read: `handle_read_script_draft()` em `blender_addon/handlers.py:1740`.
- Payload do text block: `_draft_payload_from_block()` em `blender_addon/handlers.py:1406`.

Props persistidas no Text block:

- `_draft_description`
- `_draft_tree_name`
- `_draft_version`
- `_draft_revision_parent`
- `_draft_revision_validity`
- `_draft_last_valid_revision`
- `_draft_expected_parameter_refs`
- `_draft_expected_focus_regions`
- `_draft_edit_mode`
- `_draft_goal_mode`
- `_draft_goal_guidance`
- `_draft_archive_path`

Status: ativo e deve continuar fonte de verdade do script vivo.

### Draft history

Local: `runtime/draft_history/<session_id>/...`.

Codigo:

- Arquivamento chamado em `handle_write_script_draft()` quando `session_id/project_root` entram no input, em `blender_addon/handlers.py:1693`.

Status: ativo. Bom para comparar/reparar falhas.

### Snapshots

Local: `runtime/snapshots/<session_id>/snap_*_rN.blend`.

Codigo:

- `take_snapshot()` em `blender_addon/snapshot_manager.py:78`.
- `list_snapshots()` em `blender_addon/snapshot_manager.py:111`.
- `restore_snapshot()` em `blender_addon/snapshot_manager.py:143`.
- UI chama snapshot antes da execucao manual em `blender_addon/ui/panel.py:1287`.

Status: ativo na UX do ciclo de trabalho. Deve ser preservado.

## 2. Estado em memoria

### UI SESSION

Codigo:

- Singleton `SESSION` em `blender_addon/ui/chat_session.py:226`.
- Mensagens, tool status, streaming, screenshots, arquivos, tokens e notices em `blender_addon/ui/chat_session.py:74`.

Status: ativo. Transiente, nao deve ser fonte duravel.

Risco:

- `SESSION` tambem guarda mensagens visiveis enquanto JSONL e V1 guardam historico. A sincronizacao com disco acontece em `ui/panel.py:353`.

### AgentRuntime per-turn

Codigo:

- Reset por turno em `blender_addon/agent_runtime.py:265`.
- Campos: `_current_turn_tools`, `_read_call_counts`, `_draft_tool_policy`, `_draft_attempt_state`, `_session_state`, `_session_memory`.

Status: ativo. Necessario, mas acoplado.

Risco:

- `_session_state` e uma projecao flat de V1, mas varios modulos tratam como se fosse estado proprio.

### Runtime flat state

Codigo:

- Default em `state_ops.default_state()` em `blender_addon/runtime/state_ops.py:44`.
- Projection V1 -> flat em `Runtime._runtime_state_from_v1()` em `blender_addon/runtime/core.py:640`.
- Overlay V1 em `Runtime._overlay_v1_session_view()` em `blender_addon/runtime/core.py:543`.
- Persistencia volta para V1 em `Runtime._sync_v1_session()` em `blender_addon/runtime/core.py:488`.

Campos importantes:

- `session_id`
- `blend_path`
- `debug_mode`
- `explicit_override_mode`
- `mcp_write_enabled`
- `simulate_bridge_failure`
- `last_scene_summary`
- `last_gn_summary`
- `recent_actions`
- `last_target_tree`
- `turn_counter`
- `last_failure`
- `session_memory`
- `structural_index`
- `tree_structural_memory`
- `tree_change_markers`
- `chat_history`

Status: ativo como adapter, mas transicional.

Risco:

- Pode parecer fonte de verdade, mas hoje deveria ser visto como view/adapter de `Session`.

## 3. Estados de trabalho que se sobrepoem

### ExecutionState.phase

Definido em `EXECUTION_PHASES` em `blender_addon/session/schema.py:51`.

Valores:

- `idle`
- `reading`
- `executing`
- `drafting`
- `failed`
- `halted`

Uso:

- Router ainda olha `session.execution_state.phase`, especialmente `drafting` em `blender_addon/runtime/router.py:466`.

Risco:

- `runtime/state_machine.py` ainda fala de `awaiting_confirmation`, mas esse valor nao esta mais em `EXECUTION_PHASES`.

### ExecutionState.session_state

Definido em `SESSION_STATES` em `blender_addon/session/schema.py:78`.

Valores:

- `IDLE`
- `EXPLORING`
- `DRAFTING`
- `PENDING_USER_EXECUTION`
- `REPAIRING`
- `STRATEGY_PROPOSED`
- `STRATEGY_APPROVED`
- `RESOLVED`

Uso:

- Hidrata do `SessionStateStore`.
- Usado em `_workspace_goal_mode()` para distinguir reparo e escrita em `blender_addon/runtime/handlers/__init__.py:319`.

Risco:

- Duplica o arquivo dedicado `runtime/session_state`.

### work_cycle_phase

Definido por `WorkCyclePhase` em `blender_addon/session/schema.py:95`.

Valores:

- `idle`
- `pending_user_execution`
- `executing`
- `awaiting_feedback`

Uso:

- Estado de UX do painel, nao deveria decidir arquitetura do handler.

Risco:

- Nome parecido com `ExecutionState.phase`, mas sem o mesmo significado.

## 4. Estado de draft

Duravel/Blender:

- Conteudo real: `GN_Agent_Draft` no Text Editor.
- Metadata: custom props `_draft_*`.

Duravel/session:

- `ExecutionState.current_draft`
- `draft_revision`
- `draft_block_name`
- `draft_target_tree`
- `last_executed_revision`
- `last_execution_outcome`
- `last_execution_notes`
- `retry_requires_draft_change`
- `pending_draft_action`
- `pending_draft_prompt`
- `draft_edit_mode`
- `post_failure_state`
- `approved_strategy_label`
- `pending_user_decision`
- `draft_revisions`
- `current_revision`

Codigo:

- Campos em `blender_addon/session/schema.py:559`.
- Sincronizacao por read de Text Editor em `drafting._load_draft_workspace_state()` em `blender_addon/runtime/handlers/drafting.py:1807`.
- Write metadata em `handle_write_script_draft()` em `blender_addon/handlers.py:1676`.

Risco principal:

- Ha tres copias parciais da verdade: Text block props, `ExecutionState.current_draft`, e `draft_history`. O conteudo do script so existe como verdade no Text block/draft_history.

## 5. Estado de memoria da arvore

Campos:

- `session_memory.target_tree`
- `session_memory.relevant_nodes`
- `local_scope`
- `structural_index`
- `tree_structural_memory`
- `tree_change_markers`
- `baseline_workspace`

Codigo:

- Operacoes em `blender_addon/runtime/state_ops.py:136`.
- Validacao de target/relevant nodes em `state_ops.validate_session_memory_gn()` em `blender_addon/runtime/state_ops.py:309`.
- Atualizacao por ferramenta em `AgentRuntime._update_operational_state_from_tool()` em `blender_addon/agent_runtime.py:1607`.
- Build de memoria estrutural em `RuntimeDispatcher._build_tree_structural_memory()` em `blender_addon/runtime_dispatch.py:1381`.
- Reuso/rebuild em `_load_tree_structural_memory()` em `blender_addon/runtime_dispatch.py:1554`.

Risco principal:

- `tree_structural_memory` pode ser fresh, reused, stale ou falhar por `simulate_bridge_failure`. O nome `structural_memory_ready` no draft nao garante que o modelo leu a arvore inteira naquele turno.

## 6. Flags e controles

UI props:

- `chat_debug_mode`
- `chat_explicit_override_mode`
- `chat_mcp_write_enabled`
- `chat_drafting_mode`
- `chat_simulate_bridge_failure`

Codigo:

- Registro em `blender_addon/ui/panel.py:1977`.
- Aplicacao em `blender_addon/ui/advanced.py:26`.
- `_runtime_set_modes()` em `blender_addon/ui/panel.py:464`.
- `Runtime.set_modes()` em `blender_addon/runtime/core.py:956`.

Risco principal:

- `simulate_bridge_failure` bloqueia `build_tree_structural_memory` em `AgentRuntime._execute_tool()` em `blender_addon/agent_runtime.py:1119`. Se UI e runtime divergirem, o agente fica cego enquanto a UI parece normal.

## 7. PendingUserDecision

Codigo:

- Schema em `blender_addon/session/schema.py:180`.
- Helper `set_pending_decision()` em `blender_addon/runtime/pending_decision.py:17`.
- Resolver pre-router em `AgentRuntime.run_turn()` em `blender_addon/agent_runtime.py:469`.

Status:

- Ativo e conceitualmente correto.

Risco:

- Ainda convive com regex em router e `_workspace_goal_mode()`, entao nem toda decisao humana e resolvida apenas por estado.

## 8. Ambiguidades que mais afetam o uso

- `phase`, `session_state` e `work_cycle_phase` parecem estados do mesmo sistema, mas respondem a perguntas diferentes.
- `runtime_state` flat e V1 session convivem; um bug pode vir de qualquer lado.
- `draft_revision` e `current_revision` podem confundir revisao real do Text block com estado de painel.
- `tree_structural_memory` pode ser cache ou leitura nova; a UI/journal precisa dizer qual foi.
- `chat_history` aparece no JSONL, no V1 hidratado e no `SESSION`.
- Flags debug existem em UI Scene props, V1 `UIState` e runtime state.

## 9. Fontes de verdade recomendadas hoje

- Script vivo: `GN_Agent_Draft` no Text Editor.
- Historico visivel: `runtime/chat_history/<session_id>.jsonl`.
- Sessao estruturada: `runtime/sessions_v1/*.json`.
- Estado alto nivel: `runtime/session_state/<session_id>.json`, espelhado em `ExecutionState.session_state`.
- Evidencia/debug: `runtime/journal/runs/<session_id>/<run_id>.jsonl`.
- Snapshot de seguranca: `runtime/snapshots/<session_id>/`.

## 10. Estado que deveria ser isolado antes de grandes mudancas

- Contrato de draft attempt: hoje em `AgentRuntime`.
- Draft pipeline state: hoje em `drafting.py`.
- Prepared context/structural memory: hoje em `runtime_dispatch.py`.
- UI work-cycle state: hoje misturado em `ui/panel.py`.
- Flat runtime state: manter como adapter, nao como dominio.
