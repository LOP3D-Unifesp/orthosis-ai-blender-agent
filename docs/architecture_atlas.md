# Architecture Atlas

Este atlas descreve a arquitetura atual do addon como ela existe hoje. Ele nao
propoe uma refatoracao nova; separa camadas ativas, shims/legado, partes boas,
acoplamentos e fronteiras que valem preservar.

## 1. Mapa rapido

Fluxo principal do produto:

```text
Blender UI
  -> AgentRuntime.run_turn
  -> TurnRouter.classify
  -> dispatch_turn / workspace handler
  -> prompt/context/policy
  -> runtime_agent_loop.agent_loop
  -> AgentRuntime._execute_tool
  -> tools.dispatch_tool_raw socket
  -> server.BlenderBridgeServer
  -> Runtime.execute_tool_call
  -> RuntimeDispatcher.execute
  -> handlers.py / capture.py / Blender bpy
```

Persistencia e observabilidade ficam ao lado do fluxo:

```text
Session V1 JSON
Chat JSONL
SessionStateStore
OperationJournal
Draft Text block + draft_history
Snapshots
```

Referencias centrais:

- UI normal: `blender_addon/ui/panel.py:904`, `blender_addon/ui/panel.py:815`, `blender_addon/ui/panel.py:965`.
- Runtime de turno: `blender_addon/agent_runtime.py:254`.
- Router: `blender_addon/runtime/router.py:422`.
- Dispatcher de handlers: `blender_addon/runtime/handlers/__init__.py:241`.
- Workspace handler: `blender_addon/runtime/handlers/workspace.py:78`.
- Draft internals: `blender_addon/runtime/handlers/drafting.py:1807`, `blender_addon/runtime/handlers/drafting.py:1900`.
- Loop do modelo: `blender_addon/runtime_agent_loop.py:180`.
- Socket client: `blender_addon/tools.py:511`.
- Socket server: `blender_addon/server.py:33`.
- Runtime/tool bridge: `blender_addon/runtime/core.py:1460`.
- Tool dispatcher: `blender_addon/runtime_dispatch.py:48`.
- Handlers bpy: `blender_addon/handlers.py:69`, `blender_addon/handlers.py:1503`.

## 2. Camadas ativas

### UI e ciclo de trabalho

Ativo:

- `blender_addon/ui/panel.py` e a superficie principal do usuario. Ele guarda input, mensagens visiveis, anexos, screenshots, botoes de execucao manual, feedback e snapshot.
- `blender_addon/ui/chat_session.py` contem o singleton `SESSION`, estado em memoria da UI e sanitizacao para impedir dump de codigo no painel.
- `blender_addon/ui/advanced.py` controla flags de runtime, incluindo `simulate_bridge_failure`.
- `blender_addon/__init__.py` registra UI/servidor e limpa contexto em load/save de arquivo.

Bom:

- Separar `SESSION` sem `bpy` em `ui/chat_session.py` facilita teste.
- O painel ja modela o ciclo real do designer: draft pronto, execucao manual, resultado, revert.

Acoplado demais:

- `ui/panel.py` tem 1752 linhas e mistura render de UI, chamadas de runtime, snapshot, execucao manual, hidratacao de historico e feedback.
- Flags da UI precisam atravessar `Scene` props, `runtime_set_modes`, V1 `UIState` e runtime flat state; isso aumenta risco de UI mostrar uma coisa e runtime usar outra.

Preservar:

- `SESSION` como estado transiente de UI.
- Sanitizacao de codigo em `ui/chat_session.py`.
- UX de snapshot antes da execucao manual.

Isolar/reescrever depois:

- Separar operadores de ciclo de trabalho e snapshot de `ui/panel.py`.
- Concentrar flags debug em uma unica fonte de verdade visivel.

### AgentRuntime

Ativo:

- `AgentRuntime.run_turn()` e o orquestrador do turno em `blender_addon/agent_runtime.py:254`.
- Ele carrega V1, flat runtime projection, historico recente, pending decisions, fast paths, router, modelo, dispatch, journal e persistencia.
- `_execute_tool()` em `blender_addon/agent_runtime.py:1066` e a ponte entre o modelo e a superficie de ferramentas.
- `_enforce_draft_tool_policy()` em `blender_addon/agent_runtime.py:1399` controla budget/contrato de leitura-escrita no draft.

Bom:

- Ha um ponto unico onde chamadas de ferramenta do agente sao normalizadas e auditadas.
- O contrato de draft impede `write_script_draft` sem contexto minimo.
- Ferramentas perigosas (`execute_code`, `make_plan`, etc.) sao bloqueadas no runtime draft-first.

Acoplado demais:

- `agent_runtime.py` tem 1857 linhas e sabe sobre UI, sessao, journal, router, prompt, policy de draft, socket, memoria operacional, modelo e postprocessamento.
- A politica de draft mora no orquestrador geral; isso torna mudancas de draft arriscadas para todo o runtime.

Preservar:

- `run_turn()` como ponto unico de entrada do produto.
- `_execute_tool()` como guarda de seguranca e observabilidade.

Isolar/reescrever depois:

- Extrair contrato/politica de draft para modulo proprio.
- Extrair sincronizacao de memoria operacional de `_update_operational_state_from_tool()`.

### Router e handlers

Ativo:

- `TurnRouter.classify()` em `blender_addon/runtime/router.py:429`.
- `dispatch_turn()` em `blender_addon/runtime/handlers/__init__.py:241`.
- `workspace.handle()` em `blender_addon/runtime/handlers/workspace.py:78`.
- `drafting.handle_execution_feedback()` ainda e dispatch ativo para feedback em `blender_addon/runtime/handlers/drafting.py:2532`.

Bom:

- O dispatcher tem uma superficie pequena de turn classes.
- `workspace.py` ja centraliza goal modes (`inquiry`, `diagnose_only`, `focal_correction`, `functional_expansion`, `feedback_fix`).
- `routing_obs.py` separa observabilidade do roteamento real.

Acoplado demais:

- `_workspace_goal_mode()` ainda e regex-heavy e depende de `session_state`, `post_failure_state`, pending action e texto bruto.
- `drafting.py` e o maior arquivo do projeto, com estado, prompt, diagnostico, policy, finalizacao, fallback e handlers alternativos.

Preservar:

- `TurnClass` reduzido.
- `workspace.handle(goal_mode)` como destino de convergencia.
- `PendingUserDecision` como estado conversacional em vez de regex aberta.

Isolar/reescrever depois:

- Dividir `drafting.py` por responsabilidades: estado, contexto, prompt, tool policy, feedback/failure, finalizacao.
- Fazer goal mode vir mais de estado/decision do que de regex.

### Loop do modelo e prompt

Ativo:

- `runtime_agent_loop.agent_loop()` em `blender_addon/runtime_agent_loop.py:180`.
- `model_policy.select_model()` e `select_max_tokens()` em `blender_addon/model_policy.py:26`.
- `prompt_builder.build_system_prompt()` em `blender_addon/runtime/prompt_builder.py:89`.
- `KnowledgeRetriever` em `blender_addon/knowledge/retriever.py:16`.

Bom:

- O loop para apos draft salvo ou bloqueado.
- Truncamento de resposta evita executar/salvar ferramenta incompleta.
- Prompt builder nao carrega conhecimento sozinho; recebe bundle pronto.

Acoplado demais:

- O loop conhece comportamento especial de `write_script_draft`.
- Parte do prompt de draft e montada fora de `prompt_builder`, em `drafting._build_draft_workspace_system()`.

Preservar:

- Halt-after-write.
- Sanitizacao/truncation guard.
- Budget por turn class.

Isolar/reescrever depois:

- Separar "tool-loop generico" de "comportamento especifico de draft".
- Concentrar prompt de draft em um builder dedicado.

### Superficie de ferramentas e Blender bpy

Ativo:

- `tools.TOOLS` define schemas do modelo em `blender_addon/tools.py:10`; `AGENT_TOOLS` exclui ferramentas fora do runtime draft-first em `blender_addon/tools.py:431`.
- `RuntimeDispatcher._TOOL_HANDLERS` mapeia ferramentas em `blender_addon/runtime_dispatch.py:55`.
- `handlers.py` contem reads/writes diretos em `bpy`, incluindo `handle_write_script_draft()` em `blender_addon/handlers.py:1503`.
- `capture.py` serializa cena e node trees.
- `safety_policy.py` define auto-apply/confirm/override.

Bom:

- `RuntimeDispatcher` e uma superficie canonica para chamadas `runtime_tool_call`.
- `safety_policy` e pequeno, legivel e central.
- `write_script_draft` valida completude, dominio GN e regressao antes de sobrescrever Text Editor.

Acoplado demais:

- `runtime_dispatch.py` tem 2127 linhas e mistura registry, resolucao de workspace, memoria estrutural, interpretacao semantica, draft context e ferramentas.
- `handlers.py` tem 1573 linhas e mistura captura focal, mutacoes antigas, introspeccao, execucao direta e draft text-block.
- O draft depende ao mesmo tempo de `runtime_dispatch.prepare_draft_context`, `handlers.write_script_draft`, `AgentRuntime` policy e `drafting.py`.

Preservar:

- `RuntimeDispatcher.execute()` como entrada unica server-side.
- `write_script_draft` como unico ponto que escreve no Text Editor.
- `safety_policy` central.

Isolar/reescrever depois:

- Extrair `prepare_draft_context` e structural memory de `runtime_dispatch.py`.
- Separar handlers read-only, mutacao legada, draft text-block e introspeccao em arquivos diferentes.

### Sessao, memoria e journal

Ativo:

- `Session` V1 em `blender_addon/session/schema.py:875`.
- `SessionV1Store` em `blender_addon/session/store.py:73`.
- `ChatHistoryStore` em `blender_addon/session/chat_store.py:26`.
- `SessionStateStore` em `blender_addon/session/session_state_store.py:34`.
- `state_ops.py` opera o flat runtime state.
- `OperationJournal` em `blender_addon/operation_journal.py:199`.

Bom:

- Chat visivel e JSONL append-only separado do JSON da sessao.
- V1 session e dataclass estruturada.
- Journal por run/goal e essencial para debugar sessoes reais.
- Dedicated `session_state` ajuda no repair loop.

Acoplado demais:

- Existem tres conceitos de estado de trabalho: `ExecutionState.phase`, `ExecutionState.session_state` e `work_cycle_phase`.
- Existe flat runtime projection alem da sessao V1; o proprio codigo chama isso de shim/adapter.
- A memoria estrutural vive como operational_state, flat state e prompt renderizado.

Preservar:

- V1 schema.
- Chat JSONL.
- Journal.
- `PendingUserDecision`.
- Text Editor como fonte de verdade do script.

Isolar/reescrever depois:

- Reduzir flat runtime state a adaptador interno sem semantica propria.
- Documentar uma unica maquina de estado de trabalho para decisao de handler.

## 3. O que parece legado ou transicional

- `runtime/state_machine.py` fala de `awaiting_confirmation`, mas `ExecutionState.EXECUTION_PHASES` nao inclui mais esse phase. Parece legado de mutacao direta.
- `workspace._delegate_legacy()` existe, mas `GOAL_CONFIGS` atuais nao usam `legacy_handler`.
- `drafting.handle_draft_workspace()` ainda existe, mas o dispatch atual passa por `workspace._handle_draft_goal()`.
- `handlers.HANDLERS` ainda permite comandos diretos antigos no socket quando `cmd_type` nao e `runtime_tool_call`.
- `make_plan`, `execute_code`, `apply_simulator_payload`, `rename_object`, `move_to_collection` ainda existem em schemas/handlers/safety, mas ficam bloqueados para o agente draft-first.
- Comentarios de "legacy runtime still authoritative" aparecem no core, mas o caminho atual projeta V1 para flat state.
- Diagnosticos `_diag(...)` e prints em load/save/session store parecem instrumentacao temporaria.

## 4. O que esta bom

- O produto convergiu para draft-first: o agente salva script no Text Editor e nao executa autonomamente.
- A UI ja representa o ciclo humano real: revisar, executar manualmente, reportar resultado, reverter snapshot.
- Ha rastreabilidade forte: journal por run, chat JSONL, draft history, snapshots.
- O `PendingUserDecision` e uma boa resposta arquitetural para aprovacoes humanas.
- O renderer de arvore preserva nomes, links, sockets e identifiers em texto compacto.
- `write_script_draft` e uma barreira util contra sobrescrita ruim.

## 5. O que esta acoplado demais

- Draft atravessa quatro arquivos grandes ao mesmo tempo: `drafting.py`, `agent_runtime.py`, `runtime_dispatch.py`, `handlers.py`.
- Estado de reparo atravessa `ExecutionState`, `SessionStateStore`, `routing_obs`, `_workspace_goal_mode`, `pending_decision`, `drafting.py` e `AgentRuntime`.
- Memoria da arvore atravessa runtime flat state, operational state, structural memory store, baseline workspace, tree renderer e prompt.
- UI flags atravessam Scene props, socket, local runtime fallback, V1 `UIState` e runtime state.
- O loop generico do modelo tem comportamento especial para uma ferramenta especifica (`write_script_draft`).

## 6. Conclusao arquitetural

O addon nao esta "todo ruim". Ele tem nucleos bons: draft-first, Text Editor como fonte de verdade, journal, V1 session, chat JSONL, safety policy e pending decisions.

O problema e que esses nucleos foram sendo adicionados sem ainda remover as camadas antigas. O resultado e um sistema funcional, mas com muita sobreposicao: handler novo chamando internals antigos, estado V1 projetado em flat state, router regex convivendo com estado conversacional, e draft dividido entre contexto, prompt, policy e validacao em arquivos diferentes.

Se for refatorar, o alvo mais seguro nao e reescrever tudo. O alvo e isolar o subproduto "draft generation" e suas entradas deterministicas, preservando runtime, sessao, journal, Text Editor e safety.
