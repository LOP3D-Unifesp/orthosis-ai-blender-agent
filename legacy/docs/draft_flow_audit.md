# Draft Flow Audit

> Legacy-context note for `codex/biomodel-source-migration`: this document audits the old draft-mutation flow. It is not the governing architecture for biomodel source mode. For the accepted source-mode boundary, see `docs/BIOMODEL_SOURCE_MODE_DECISION.md`.

## 1. Entrada do usuario

- Entrada normal da UI: `CHAT_OT_SendMessage.execute()` em `blender_addon/ui/panel.py:965` chama `_send_user_message()` em `blender_addon/ui/panel.py:904`.
- `_send_user_message()` registra a mensagem do usuario, limpa `scene.chat_input`, cria uma thread e aponta para `_run_chat_turn()` em `blender_addon/ui/panel.py:952`.
- `_run_chat_turn()` e a entrada de runtime da UI. Ela chama `runtime.run_turn(...)` em `blender_addon/ui/panel.py:870`.
- Feedback de execucao tambem entra pelo mesmo funil: `BLEND_OT_send_and_revert.execute()` monta uma mensagem estruturada em `blender_addon/ui/panel.py:1485` e chama `_send_user_message()`.
- Entrada principal do runtime: `AgentRuntime.run_turn()` em `blender_addon/agent_runtime.py:254`.

## 2. Caminho principal ativo

Pipeline ativa para criar/refazer/ajustar draft:

1. `AgentRuntime.run_turn()` reseta estado por turno em `blender_addon/agent_runtime.py:265`, carrega sessao V1 em `blender_addon/agent_runtime.py:284`, carrega runtime state em `blender_addon/agent_runtime.py:364` e registra `simulate_bridge_failure_active` se o flag estiver ligado em `blender_addon/agent_runtime.py:398`.
2. O roteador ativo e `TurnRouter.classify()` em `blender_addon/runtime/router.py:429`. Em fase `drafting`, quase tudo que nao e feedback/factual/state-control cai em `TurnClass.DRAFT_WORKSPACE` em `blender_addon/runtime/router.py:506`.
3. `AgentRuntime.run_turn()` instancia o roteador em `blender_addon/agent_runtime.py:577`, chama `classify()` em `blender_addon/agent_runtime.py:578`, cria `TurnContext` em `blender_addon/agent_runtime.py:664` e chama `dispatch_turn()` em `blender_addon/agent_runtime.py:700`.
4. `dispatch_turn()` fica em `blender_addon/runtime/handlers/__init__.py:241`. Para `DRAFT_WORKSPACE`, ele chama `workspace.handle(ctx, _workspace_goal_mode(...))` em `blender_addon/runtime/handlers/__init__.py:252`.
5. `_workspace_goal_mode()` em `blender_addon/runtime/handlers/__init__.py:309` escolhe `diagnose_only`, `focal_correction`, `functional_expansion` ou `feedback_fix`.
6. `workspace.handle()` em `blender_addon/runtime/handlers/workspace.py:78` escolhe `GOAL_CONFIGS` em `blender_addon/runtime/handlers/workspace.py:33`. Para modos de draft, chama `_handle_draft_goal()` em `blender_addon/runtime/handlers/workspace.py:206`.
7. `_handle_draft_goal()` chama `_load_draft_workspace_state()` em `blender_addon/runtime/handlers/drafting.py:1807`, `_build_draft_workspace_system()` em `blender_addon/runtime/handlers/drafting.py:1900`, `_draft_workspace_tool_policy()` em `blender_addon/runtime/handlers/drafting.py:2109`, depois `ctx.call_agent_loop()` em `blender_addon/runtime/handlers/workspace.py:232`.
8. `TurnContext.call_agent_loop()` em `blender_addon/runtime/handlers/__init__.py:87` chama `AgentRuntime._agent_loop()` em `blender_addon/agent_runtime.py:993`.
9. `AgentRuntime._agent_loop()` aplica exclusoes de produto e chama `runtime_agent_loop.agent_loop()` em `blender_addon/agent_runtime.py:1008`.
10. `agent_loop()` em `blender_addon/runtime_agent_loop.py:180` faz as rodadas do modelo. A chamada real ao modelo fica em `_stream_with_retry()` / `_request_with_retry()` em `blender_addon/runtime_agent_loop.py:216` e `blender_addon/runtime_agent_loop.py:220`.
11. Quando o modelo chama ferramenta, `agent_loop()` chama `runtime._execute_tool()` em `blender_addon/runtime_agent_loop.py:358`.
12. `AgentRuntime._execute_tool()` em `blender_addon/agent_runtime.py:1066` aplica `_enforce_draft_tool_policy()` em `blender_addon/agent_runtime.py:1077`, normaliza input em `blender_addon/agent_runtime.py:1093`, e chama `dispatch_tool_raw()` em `blender_addon/agent_runtime.py:1140`.
13. `dispatch_tool_raw()` em `blender_addon/tools.py:511` manda `runtime_tool_call` pelo socket para o Blender.
14. No lado Blender, `Runtime.execute_tool_call()` em `blender_addon/runtime/core.py:1460` chama `RuntimeDispatcher.execute()` em `blender_addon/runtime/core.py:1627`.
15. `RuntimeDispatcher.execute()` em `blender_addon/runtime_dispatch.py:94` usa `_TOOL_HANDLERS`. `write_script_draft` vai para `_tool_write_script_draft()` em `blender_addon/runtime_dispatch.py:233`, que chama `handlers.handle_write_script_draft()`.
16. `handle_write_script_draft()` em `blender_addon/handlers.py:1503` valida e escreve no Text Editor: `bpy.data.texts.get(block_name)` em `blender_addon/handlers.py:1666`, cria se necessario em `blender_addon/handlers.py:1669`, limpa e escreve com `text_block.write(code)` em `blender_addon/handlers.py:1673`.
17. Apos sucesso/bloqueio, `agent_loop()` encerra ou continua conforme `write_script_draft` em `blender_addon/runtime_agent_loop.py:366`. A finalizacao do workspace fica em `_finalize_draft_workspace_attempt()` em `blender_addon/runtime/handlers/drafting.py:2236`.

## 3. Caminhos alternativos encontrados

- Ativo: `DRAFT_WORKSPACE -> workspace.handle() -> _handle_draft_goal() -> drafting internals`. Este e o caminho principal hoje.
- Ativo, mas separado: `EXECUTION_FEEDBACK -> drafting.handle_execution_feedback()` em `blender_addon/runtime/handlers/__init__.py:253` e `blender_addon/runtime/handlers/drafting.py:2532`. Ele registra feedback/diagnostico e pode preparar estado de reparo; nao e o caminho normal de escrita direta de draft.
- Ativo para perguntas factuais durante drafting: router retorna `CONTEXT_INQUIRY` em `blender_addon/runtime/router.py:483` ou `blender_addon/runtime/router.py:492`; `workspace._maybe_tree_render_for_factual_inquiry()` injeta snapshot de arvore em `blender_addon/runtime/handlers/workspace.py:103`.
- Alternativo/parece legado: `drafting.handle_draft_workspace()` em `blender_addon/runtime/handlers/drafting.py:2489`. Ele ainda monta o mesmo tipo de pipeline, mas `dispatch_turn()` nao chama esse handler diretamente no caminho atual.
- Alternativo/ponte legada: `workspace._delegate_legacy()` em `blender_addon/runtime/handlers/workspace.py:194`. Existe para `legacy_handler`, mas os `GOAL_CONFIGS` atuais de draft nao definem `legacy_handler`, entao nao entra no caminho normal.
- Ponte de ferramentas: `handlers.HANDLERS` em `blender_addon/handlers.py:1776` ainda registra `write_script_draft` em `blender_addon/handlers.py:1790`, mas no fluxo do agente ele normalmente chega via `RuntimeDispatcher`, nao por chamada direta do handler registry.

## 4. Estado e memoria injetados no draft

- `has_existing_draft`: nasce de `bool(state.content.strip())`. O conteudo vem de `read_script_draft` dentro de `_load_draft_workspace_state()` em `blender_addon/runtime/handlers/drafting.py:1807`. E passado para `prepare_draft_context` em `blender_addon/runtime/handlers/drafting.py:294`, para `_draft_workspace_tool_policy()` em `blender_addon/runtime/handlers/workspace.py:213`, e recebido por `RuntimeDispatcher._prepare_draft_context()` em `blender_addon/runtime_dispatch.py:768`.
- `stored_live_node_refs`: vem do payload do Text Editor em `_draft_payload_from_block()` (`live_node_refs`) em `blender_addon/handlers.py:1426`, e entra no estado em `blender_addon/runtime/handlers/drafting.py:1846`. Depois e injetado no system prompt em `blender_addon/runtime/handlers/drafting.py:2032`, enviado ao `prepare_draft_context` em `blender_addon/runtime/handlers/drafting.py:295`, e usado para cobertura em `blender_addon/runtime_dispatch.py:688`.
- `stored_expected_parameter_refs`: vem das props do Text Editor em `blender_addon/handlers.py:1427`, entra no estado em `blender_addon/runtime/handlers/drafting.py:1847`, e e injetado no prompt em `blender_addon/runtime/handlers/drafting.py:2034`. Tambem passa para `prepare_draft_context` em `blender_addon/runtime/handlers/drafting.py:296` e para cobertura em `blender_addon/runtime_dispatch.py:689`.
- `structural_memory_ready`: e estado interno do contrato de tentativa. Ele e inicializado a partir de `policy["fresh_structural_memory"]` em `AgentRuntime._ensure_draft_attempt_state()` em `blender_addon/agent_runtime.py:1279`, pode ser marcado por `prepare_draft_context` em `blender_addon/agent_runtime.py:1330`, por `build_tree_structural_memory` em `blender_addon/agent_runtime.py:1341`, e bloqueia escrita em `_draft_write_contract_block_reason()` em `blender_addon/agent_runtime.py:1384`.
- `REPAIRING`: e derivado por `compute_next_state()` quando `retry_requires_draft_change`, falha ou `last_failure` existem em `blender_addon/session/session_state_store.py:130` e `blender_addon/session/session_state_store.py:164`. O roteamento le esse valor via `meta.session_state`; `_workspace_goal_mode()` testa `REPAIRING` em `blender_addon/runtime/handlers/__init__.py:319` e muda o modo de draft em `blender_addon/runtime/handlers/__init__.py:455`.
- `functional_expansion`: e um goal mode em `GOAL_CONFIGS` em `blender_addon/runtime/handlers/workspace.py:58`. Pode vir de pedido explicito "do zero" em `blender_addon/runtime/handlers/__init__.py:451`, de `intent == "draft_write"` em `blender_addon/runtime/handlers/__init__.py:487`, ou da deteccao em `drafting._detect_draft_goal_mode_from_source()` em `blender_addon/runtime/handlers/drafting.py:1283`.
- `economy_retry`: e calculado por `_is_economy_retry_turn()` em `blender_addon/runtime/handlers/drafting.py:1217` quando ha pending action, pedido de retry, `retry_requires_draft_change` ou `pending_draft_action`. Ele entra no estado em `blender_addon/runtime/handlers/drafting.py:1811`, reduz knowledge em `blender_addon/runtime/handlers/drafting.py:1904`, adiciona instrucao especial ao system prompt em `blender_addon/runtime/handlers/drafting.py:1987`, e restringe leituras em `_enforce_draft_tool_policy()` em `blender_addon/agent_runtime.py:1399`.

## 5. Validacao atual

- Antes da ferramenta escrever, existe um contrato de tentativa em `AgentRuntime`: `_draft_write_contract_block_reason()` em `blender_addon/agent_runtime.py:1376` bloqueia escrita se faltar fonte lida, alvo resolvido, memoria estrutural, contexto preparado ou evidencia.
- A politica de ferramenta fica em `_enforce_draft_tool_policy()` em `blender_addon/agent_runtime.py:1399`. Em retry economico, broad reads sao bloqueados, com excecao de uma leitura de `build_tree_structural_memory` quando falta memoria fresca em `blender_addon/agent_runtime.py:1411`.
- `handle_write_script_draft()` valida completude do script com `_infer_draft_revision_validity()` em `blender_addon/handlers.py:1080` e bloqueia revisoes nao validas em `blender_addon/handlers.py:1560`.
- Valida alvo/dominio GN com `_draft_domain_reject_reason()` em `blender_addon/handlers.py:1327`, chamado em `blender_addon/handlers.py:1580`.
- Valida regressao semantica contra o draft vivo com `_draft_semantic_regression_reason()` em `blender_addon/handlers.py:1232`, chamado em `blender_addon/handlers.py:1622`; bloqueia em `blender_addon/handlers.py:1632`.
- A validacao atual confirma forma, alvo, refs existentes e regressao de cobertura. Ela nao prova que a logica funcional do script vai produzir o efeito geometrico esperado no Blender.

## 6. Pontos de ambiguidade

- Existem duas pipelines de draft muito parecidas: a ativa via `workspace._handle_draft_goal()` e a alternativa `drafting.handle_draft_workspace()`. A segunda parece legado/compatibilidade, mas ainda esta no codigo.
- `functional_expansion` nao significa sempre "do zero": quando existe draft, `RuntimeDispatcher._draft_goal_guidance()` descreve extensao do mesmo draft em `blender_addon/runtime_dispatch.py:753`.
- `structural_memory_ready` nao significa necessariamente "a arvore inteira foi lida agora pelo modelo". Pode vir de `prepare_draft_context`, memoria reconstruida/reusada, ou `build_tree_structural_memory`.
- `prepare_draft_context` mistura varias responsabilidades: resolve workspace, carrega/reconstroi memoria estrutural, parametros, fase, papeis clinicos, interpretacao, cobertura e write gate em `blender_addon/runtime_dispatch.py:761`.
- `stored_live_node_refs` e `stored_expected_parameter_refs` sao memoria persistida do draft vivo; elas podem proteger contra regressao, mas tambem podem carregar foco antigo para um pedido novo se o goal mode for interpretado como refinamento.
- O modelo recebe contexto em texto no system prompt, incluindo render compacto de arvore em `_build_draft_workspace_system()` em `blender_addon/runtime/handlers/drafting.py:2057` a `blender_addon/runtime/handlers/drafting.py:2094`. Nao existe um `DraftSpec` deterministico separado do prompt.
- `economy_retry` altera profundamente o conjunto de ferramentas disponiveis, mas ainda passa pelo mesmo handler de draft. Isso torna o comportamento dependente de flags de estado pendente, nao apenas da mensagem do usuario.

## 7. Conclusao: qual e a pipeline real hoje?

A pipeline real hoje e:

`UI prompt -> _send_user_message -> _run_chat_turn -> AgentRuntime.run_turn -> TurnRouter.classify -> dispatch_turn -> workspace.handle -> _handle_draft_goal -> drafting._load_draft_workspace_state -> drafting._build_draft_workspace_system -> RuntimeDispatcher.prepare_draft_context/build_tree_structural_memory -> drafting._draft_workspace_tool_policy -> TurnContext.call_agent_loop -> AgentRuntime._agent_loop -> runtime_agent_loop.agent_loop -> AgentRuntime._execute_tool -> dispatch_tool_raw socket -> Runtime.execute_tool_call -> RuntimeDispatcher._tool_write_script_draft -> handlers.handle_write_script_draft -> Blender Text Editor GN_Agent_Draft -> drafting._finalize_draft_workspace_attempt`.

Ou seja: o fluxo de draft ativo nao e uma funcao unica simples. Ele e um wrapper novo de workspace chamando varias funcoes internas antigas de `drafting.py`, com validacao em dois niveis: contrato/politica antes da ferramenta e validacao do script dentro de `handle_write_script_draft()`.
