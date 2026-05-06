# Refactor Decision Matrix

Esta matriz ajuda a decidir onde mexer depois da auditoria. Ela nao e um plano
de implementacao; e um mapa de decisao para evitar refatorar no escuro.

## 1. Legenda

- `Preservar`: manter como base; mexer so com testes.
- `Isolar`: separar fronteira/responsabilidade antes de mudar comportamento.
- `Reescrever`: substituir internals com contrato preservado.
- `Aposentar depois`: manter por compatibilidade ate cobrir/remover chamada.
- `Nao priorizar`: deixar quieto por enquanto.

## 2. Matriz por componente

| Area | Arquivos | Ativo? | Valor | Dor atual | Decisao | Risco de mexer |
|---|---|---:|---|---|---|---|
| UI chat/transiente | `ui/chat_session.py` | Sim | Estado de painel testavel, sanitiza codigo | Baixa | Preservar | Baixo |
| UI painel principal | `ui/panel.py` | Sim | Entrada principal e UX do ciclo manual | 1752 linhas, mistura UI/runtime/snapshot/feedback | Isolar | Alto |
| Advanced flags | `ui/advanced.py`, `ui/panel.py`, `runtime/core.py` | Sim | Necessario para debug | Flag pode divergir entre UI e runtime | Isolar | Medio |
| Addon lifecycle | `__init__.py` | Sim | Load/save limpa contexto e reatacha sessao | Prints DIAG e acoplamento com UI/runtime | Isolar depois | Medio |
| Socket server | `server.py` | Sim | Ponte Blender para tool calls | Ainda aceita comandos legacy diretos | Preservar + aposentar legacy depois | Alto |
| Tool schemas/client | `tools.py` | Sim | Contrato do modelo e socket client | Schemas incluem ferramentas bloqueadas | Preservar | Medio |
| Runtime core | `runtime/core.py` | Sim | Safety, V1 projection, tool execution, session view | Muito amplo; flat state adapter confunde | Isolar | Alto |
| AgentRuntime | `agent_runtime.py` | Sim | Orquestrador central e guarda do agente | Mistura turno, estado, draft policy, tool postprocess, modelo | Isolar | Alto |
| Model loop | `runtime_agent_loop.py` | Sim | Multi-round tools, truncation guard, halt-after-write | Conhece ferramenta especifica de draft | Preservar + isolar comportamento draft | Medio |
| Router | `runtime/router.py` | Sim | Classificacao deterministica sem LLM | Regex demais, estado insuficiente | Isolar/reescrever por etapas | Alto |
| Routing obs | `runtime/routing_obs.py` | Sim | Excelente para detectar divergencia sem mudar dispatch | Pode virar segunda logica paralela | Preservar | Baixo |
| Handler dispatcher | `runtime/handlers/__init__.py` | Sim | Superficie pequena de turn classes | `_workspace_goal_mode` e regex-heavy | Isolar | Alto |
| Workspace handler | `runtime/handlers/workspace.py` | Sim | Convergencia para goal modes explicitos | Ainda chama internals antigos de drafting | Preservar como fachada | Medio |
| Draft internals | `runtime/handlers/drafting.py` | Sim | Fluxo real de draft/feedback | 2595 linhas, muitas responsabilidades | Isolar primeiro, reescrever partes | Muito alto |
| Prepared context | `runtime_dispatch.py` | Sim | Agrega contexto deterministico da arvore | 2127 linhas, mistura dispatcher e inteligencia de contexto | Isolar | Alto |
| Bpy handlers | `handlers.py` | Sim | Acesso real a Blender e Text Editor | 1573 linhas, read/write/mutacao/legacy juntos | Isolar | Alto |
| Capture | `capture.py` | Sim | Snapshot cena/node trees | Relativamente coeso | Preservar | Medio |
| Safety policy | `safety_policy.py` | Sim | Pequeno, central, legivel | Pouca dor | Preservar | Medio |
| Session schema | `session/schema.py` | Sim | Fonte estruturada V1 | Muitos campos sobrepostos | Preservar, racionalizar depois | Alto |
| Session store | `session/store.py` | Sim | Per-file V1, quarantine, migration | DIAG prints e legacy scan complexos | Preservar + limpar depois | Medio |
| Chat store | `session/chat_store.py` | Sim | JSONL duravel e simples | Pouca dor | Preservar | Baixo |
| SessionStateStore | `session/session_state_store.py` | Sim | Estado alto nivel atomico | Duplica `ExecutionState.session_state` | Preservar por enquanto | Medio |
| State ops flat | `runtime/state_ops.py` | Sim | Funcoes puras para memoria operacional | Flat state parece dominio proprio | Isolar como adapter | Medio |
| Pending decision | `runtime/pending_decision.py` | Sim | Resolve aprovacoes por estado | Ainda convive com regex | Preservar e expandir | Medio |
| Prompt builder/knowledge | `runtime/prompt_builder.py`, `knowledge/*` | Sim | Separacao boa de prompt base e retrieval | Prompt de draft ainda fora do builder | Preservar | Baixo |
| Tree renderer | `runtime/tree_renderer.py` | Sim | Preserva nomes/sockets/links em prompt | Pouca dor | Preservar | Baixo |
| Snapshot manager | `snapshot_manager.py` | Sim | Protege ciclo manual | Integracao UI grande | Preservar | Medio |
| State machine antiga | `runtime/state_machine.py` | Pouco/nao | Historico de fase legacy | Cita `awaiting_confirmation` removido | Aposentar depois | Baixo se isolado |
| Legacy direct commands | `server.py` + `handlers.HANDLERS` | Sim para compat | Compatibilidade externa/testes | Caminho paralelo ao `runtime_tool_call` | Aposentar depois | Alto |

## 3. Decisao por sintoma

### Sintoma: drafts ruins mesmo com contexto

Mexer primeiro:

- `runtime/handlers/drafting.py`: montagem de prompt, goal mode, estado do draft.
- `runtime_dispatch.py`: `prepare_draft_context`, structural memory, parametro/interface.
- `agent_runtime.py`: contrato/policy de ferramenta.
- `handlers.py`: validacao de `write_script_draft`.

Nao mexer primeiro:

- UI geral.
- Socket server.
- Session store.

Motivo: o erro esta no pacote "contexto deterministico -> prompt -> contrato -> write", nao na entrada do usuario.

### Sintoma: agente pede confirmacao que ja deveria saber

Mexer primeiro:

- `runtime/pending_decision.py`.
- `_workspace_goal_mode()` em `runtime/handlers/__init__.py`.
- `routing_obs.py` apenas para verificar divergencias.

Nao mexer primeiro:

- `write_script_draft`.
- `RuntimeDispatcher`.

Motivo: esse sintoma e de estado conversacional/roteamento, nao de Blender API.

### Sintoma: arvore nao foi lida ou contexto stale

Mexer primeiro:

- `runtime_dispatch._load_tree_structural_memory()`.
- `runtime_dispatch._build_tree_structural_memory()`.
- `agent_runtime._enforce_draft_tool_policy()`.
- `runtime/tree_renderer.py`.
- Flag `simulate_bridge_failure` em `ui/advanced.py`, `ui/panel.py`, `runtime/core.py`, `agent_runtime.py`.

Nao mexer primeiro:

- Prompt wording.

Motivo: se a leitura nao aconteceu, prompt melhor nao resolve.

### Sintoma: UI mostra uma coisa, runtime faz outra

Mexer primeiro:

- `ui/panel.py` `_runtime_set_modes`.
- `ui/advanced.py` `CHAT_OT_ApplyModes`.
- `runtime/core.py` `set_modes()` e `get_session_state()`.
- `session/schema.py` `UIState`.

Nao mexer primeiro:

- Router/drafting.

Motivo: e divergencia de fonte de verdade de flags.

### Sintoma: estado REPAIRING/STRATEGY fica incoerente

Mexer primeiro:

- `session/session_state_store.py`.
- `runtime/pending_decision.py`.
- `runtime/routing_obs.py`.
- `_workspace_goal_mode()`.

Nao mexer primeiro:

- Text Editor write.

Motivo: problema de FSM/estado de conversa.

## 4. Priorizacao sugerida

### P0: nao quebrar invariantes boas

Preservar antes de qualquer refatoracao:

- O agente nao executa draft automaticamente.
- `GN_Agent_Draft` continua fonte de verdade do script vivo.
- Chat nao recebe script completo.
- `write_script_draft` continua validando antes de sobrescrever.
- Journal continua gravando tool calls e runtime events.
- Chat JSONL continua append-only.
- Snapshot antes de execucao manual continua funcionando.

### P1: isolar draft generation

Motivo:

- E onde o usuario sente dor agora.
- E onde ha mais acoplamento entre contexto, prompt, policy e validacao.

Primeiras fronteiras seguras:

- `DraftWorkspaceState` / load state.
- `DraftContextProvider` para `prepare_draft_context` e structural memory.
- `DraftToolPolicy` separado de `AgentRuntime`.
- `DraftPromptBuilder` separado de `drafting.py`.
- `DraftWriteValidator` mantendo `handle_write_script_draft` como shell bpy.

### P2: simplificar estado conversacional

Motivo:

- Reduz perguntas repetidas e confirmacoes perdidas.
- Tira peso de regex.

Primeiras fronteiras seguras:

- Fazer `PendingUserDecision` resolver mais casos antes do router.
- Declarar qual estado decide goal mode.
- Tratar `routing_obs` como auditoria, nao como segunda arquitetura.

### P3: aposentar legado

Depois de P1/P2 e testes:

- Remover dependencias de `runtime/state_machine.py` se nenhum caminho ativo usar.
- Fechar caminho de comandos diretos antigos no socket, se MCP/UI ja usam `runtime_tool_call`.
- Remover prints `_diag` ou colocar atras de debug flag real.
- Reduzir `handlers.py` em modulos por familia.

## 5. O que nao vale reescrever agora

- `ChatHistoryStore`: simples e duravel.
- `OperationJournal`: grande, mas essencial; mexer so se estiver quebrando.
- `safety_policy`: pequeno e correto para o momento.
- `tree_renderer`: diretamente ligado ao problema de contexto; preservar.
- `snapshot_manager`: protege o ciclo manual.
- `model_policy`: simples e suficiente.

## 6. Resposta curta para "codamos demais?"

Sim, nas camadas de draft/runtime foram adicionadas muitas protecoes sem ainda consolidar as fronteiras. Mas nao parece caso de jogar fora o sistema inteiro.

O excesso esta concentrado em quatro zonas:

- `drafting.py`
- `agent_runtime.py`
- `runtime_dispatch.py`
- `handlers.py`

O resto tem pecas boas e reutilizaveis. A estrategia mais segura e preservar o casco que funciona (UI, session, journal, Text Editor, safety, socket) e isolar o motor de draft ate ele virar uma pipeline menor e testavel.

## 7. Checklist antes de qualquer refatoracao

- Confirmar caminho ativo no `docs/draft_flow_audit.md`.
- Escolher um unico sintoma alvo.
- Escrever teste que reproduz o sintoma sem Blender quando possivel.
- Preservar payloads de journal que hoje permitem diagnostico.
- Nao mover UI, runtime, session e draft ao mesmo tempo.
- Validar no Blender real quando o sintoma depende de `bpy`, Text Editor ou node tree.
