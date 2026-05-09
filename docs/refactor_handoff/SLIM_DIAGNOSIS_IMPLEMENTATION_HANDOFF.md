# SLIM Diagnosis Implementation Handoff

## Escopo desta auditoria

Este documento registra somente o que foi implementado **depois** do diagnóstico arquitetural sobre o slim refactor do addon Blender/IA/GN.  
Não há novos commits nesta sessão; o estado atual está em **working tree local não commitado**.

## Estado atual do repositório

### `git status --short`

```text
 M CLAUDE.md
 M blender_addon/__init__.py
 M blender_addon/core/runtime.py
 D blender_addon/handler/_drafting_support.py
 M blender_addon/handler/feedback.py
 M blender_addon/handler/feedback_evidence.py
 M blender_addon/handler/workspace.py
 M blender_addon/runtime/core.py
 D blender_addon/runtime/gn_targeting.py
 M blender_addon/session/__init__.py
 M blender_addon/session/store.py
 M tests/test_dispatch_smoke.py
 M tests/test_draft_workspace_minimal_flow.py
 M tests/test_foundation_stabilization.py
 M tools/blender_runtime_validation.py
 ?? .claire/
```

### `git diff --stat`

```text
 CLAUDE.md                                  |   2 +
 blender_addon/__init__.py                  |  15 +-
 blender_addon/core/runtime.py              |  25 --
 blender_addon/handler/_drafting_support.py | 457 -----------------------------
 blender_addon/handler/feedback.py          |   4 -
 blender_addon/handler/feedback_evidence.py |  34 ---
 blender_addon/handler/workspace.py         | 350 +++++++++++++++++++---
 blender_addon/runtime/core.py              |   9 -
 blender_addon/runtime/gn_targeting.py      |  45 ---
 blender_addon/session/__init__.py          |   4 +-
 blender_addon/session/store.py             |   3 +-
 tests/test_dispatch_smoke.py               |  75 +++++
 tests/test_draft_workspace_minimal_flow.py |  15 +-
 tests/test_foundation_stabilization.py     | 152 +++++++---
 tools/blender_runtime_validation.py        |  20 +-
 15 files changed, 533 insertions(+), 677 deletions(-)
```

### `git log --oneline -8`

```text
02df9d3 refactor: replace critical regex routing with structural checks
d5d2512 cut: remove stale panel imports
8143c24 cut: remove unused safety helper
4c18cf9 cut: remove unused state ops helpers
ac01da7 cut: prune stale runtime planning helpers
540d220 cut: remove dead diagnostics and orphan helpers
7774846 cut: delete TurnRouter — 750 lines of dead routing logic
678a2d9 merge: round1+round2 server_dispatch cuts → master
```

### Arquivos alterados/criados/removidos nesta sessão

- Modificados:
  - `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\CLAUDE.md`
  - `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\blender_addon\__init__.py`
  - `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\blender_addon\core\runtime.py`
  - `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\blender_addon\handler\feedback.py`
  - `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\blender_addon\handler\feedback_evidence.py`
  - `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\blender_addon\handler\workspace.py`
  - `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\blender_addon\runtime\core.py`
  - `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\blender_addon\session\__init__.py`
  - `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\blender_addon\session\store.py`
  - `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\tests\test_dispatch_smoke.py`
  - `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\tests\test_draft_workspace_minimal_flow.py`
  - `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\tests\test_foundation_stabilization.py`
  - `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\tools\blender_runtime_validation.py`
- Removidos:
  - `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\blender_addon\handler\_drafting_support.py`
  - `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\blender_addon\runtime\gn_targeting.py`
- Criado:
  - `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\docs\refactor_handoff\SLIM_DIAGNOSIS_IMPLEMENTATION_HANDOFF.md`
- Não tocado:
  - `.claire/` continua apenas como diretório não rastreado pré-existente.

## O que foi implementado por frente

### 1. Baseline / `_refresh_baseline`

#### Implementado

- Corrigido `blender_addon/handler/workspace.py:_refresh_baseline` para usar `result.memory` em vez de persistir o envelope inteiro.
- A resolução do `tree_name` passou a usar `_target_tree_hint(ctx)` em vez de consultar `_canonical_gn_target`.
- `_handle_inquiry` deixou de fazer um refresh estrutural redundante antes de `_maybe_run_discovery`.

#### Arquivos e funções

- `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\blender_addon\handler\workspace.py`
  - `_refresh_baseline`
  - `_handle_inquiry`
  - `_maybe_run_discovery`
  - `_target_tree_hint`

#### Por que responde ao diagnóstico

- Endereça diretamente o item do diagnóstico sobre possível bug em `_refresh_baseline` salvando o envelope inteiro.
- Reduz a duplicação de leitura estrutural no caminho de inquiry, alinhando com a observação de custo/duplicação funcional.

#### Validação

- Validado com teste unitário:
  - `tests/test_foundation_stabilization.py::test_refresh_baseline_uses_structural_memory_payload_instead_of_result_envelope`
- Validado com smoke test de handler:
  - `tests/test_dispatch_smoke.py::test_inquiry_handler_uses_single_structural_read_when_refresh_is_needed`
- Validado em suíte completa:
  - `python -m pytest -q`

#### Risco / pendência / dúvida

- Não validado em Blender real.
- O bug do baseline foi coberto, mas o comportamento de inquiry ainda depende da infraestrutura de structural memory existente; convém smoke manual posterior no addon.

### 2. Entry point real do Draft Workspace

#### Implementado

- O caminho vivo passou a concentrar o fluxo de draft em `workspace.py`.
- Os helpers finais remanescentes do shim foram movidos para `workspace.py`:
  - `_handle_missing_retry_draft_source`
  - `_finalize_draft_workspace_attempt`
- O arquivo legado `_drafting_support.py` foi removido por completo.

#### Arquivos e funções

- `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\blender_addon\handler\workspace.py`
  - `_handle_draft_goal`
  - `_handle_missing_retry_draft_source`
  - `_finalize_draft_workspace_attempt`
- Removido:
  - `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\blender_addon\handler\_drafting_support.py`

#### Por que responde ao diagnóstico

- Endereça o problema “testes usando caminho diferente da produção” e o acoplamento em torno do handler paralelo legado.
- Reduz a ambiguidade sobre qual é o entry point real do Draft Workspace.

#### Validação

- Validado por suíte completa:
  - `python -m pytest -q`
- Validado por teste de ausência do módulo legado:
  - `tests/test_dispatch_smoke.py::test_legacy_drafting_support_module_is_removed`

#### Risco / pendência / dúvida

- A remoção do shim foi validada só por testes Python; não houve smoke no Blender real.
- Como o conteúdo de `_drafting_support.py` foi transplantado para `workspace.py`, o arquivo vivo cresceu bastante. Isso resolve ambiguidade de surface, mas **não** resolve ainda a meta de emagrecimento estrutural do handler.

### 3. Alinhamento entre testes e produção

#### Implementado

- Testes que chamavam `handle_draft_workspace` legado foram migrados para chamar `workspace.handle(..., goal_mode)` por um helper local de teste.
- Imports de helpers que vinham de `_drafting_support.py` foram apontados para os módulos de origem reais (`draft_state`, `draft_context`, `draft_response`, `draft_policy`, `feedback_evidence`).
- `tools/blender_runtime_validation.py` foi alinhado ao handler vivo.

#### Arquivos e funções

- `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\tests\test_draft_workspace_minimal_flow.py`
  - `_handle_draft_workspace_direct`
- `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\tests\test_foundation_stabilization.py`
  - `_handle_draft_workspace_direct`
  - vários imports trocados do shim para módulos reais
- `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\tests\test_dispatch_smoke.py`
  - substituiu teste de compatibilidade do shim por teste de remoção do módulo
- `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\tools\blender_runtime_validation.py`
  - passou a usar `handler.workspace.handle`

#### Por que responde ao diagnóstico

- Endereça diretamente o problema de os testes exercitarem outra superfície que não a produção.
- Reduz o risco de “suite verde com produção quebrada”.

#### Validação

- Validado com suíte completa:
  - `python -m pytest -q`

#### Risco / pendência / dúvida

- Ainda há helpers de teste (`_handle_draft_workspace_direct`) que espelham um pedaço de resolução do goal mode. Isso é muito melhor que o shim antigo, mas ainda não é um teste end-to-end via `AgentRuntime.run_turn`.

### 4. Tools / handlers / server_dispatch

#### Implementado

- **Nenhuma divisão estrutural** de `tools/handlers.py` ou `tools/server_dispatch.py` foi feita nesta sessão.
- Apenas `tools/blender_runtime_validation.py` foi corrigido para os imports/superfície atuais.

#### Arquivos e funções

- `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\tools\blender_runtime_validation.py`

#### Por que responde ao diagnóstico

- Responde apenas ao item pontual de import quebrado em arquivo de validação.
- **Não** responde ao diagnóstico principal sobre mega-arquivos de tools ainda centralizados.

#### Validação

- Validado indiretamente pela suíte Python.
- **Não validado** como script externo/manual do fluxo Blender runtime validation.

#### Risco / pendência / dúvida

- `tools/handlers.py` e `tools/server_dispatch.py` continuam como áreas grandes e não fatiadas.
- O script de validação foi alinhado no código, mas não foi executado manualmente nesta sessão.

### 5. `runtime/core.py` e `AgentRuntime`

#### Implementado

- Remoção do plumbing morto de canonical GN targeting:
  - `blender_addon/runtime/gn_targeting.py` removido
  - imports e campos `_canonical_gn_target*` removidos de `blender_addon/core/runtime.py`
  - consultas correspondentes removidas de `workspace.py`
- Limpeza de debug/flags mortas:
  - remoção de `USE_STRUCTURED_SESSION_V1`
  - remoção de `_active_backend_session_id`
  - remoção de prints DIAG em `blender_addon/runtime/core.py`

#### Arquivos e funções

- `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\blender_addon\core\runtime.py`
  - remoção de import `canonicalize_gn_tool_input`
  - remoção de `_canonical_gn_target`
  - remoção de `_canonical_gn_target_source`
  - remoção de `USE_STRUCTURED_SESSION_V1`
  - remoção de `_active_backend_session_id`
- `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\blender_addon\runtime\core.py`
  - remoção de prints DIAG em `v1_session_for`
- removido:
  - `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\blender_addon\runtime\gn_targeting.py`

#### Por que responde ao diagnóstico

- Endereça o item de código morto/canonical target que estava inicializado mas nunca alimentado.
- Reduz ruído em runtime, mas **não** ataca ainda o problema principal de duplicidade/bloat entre `Runtime` e `AgentRuntime`.

#### Validação

- Validado por suíte completa:
  - `python -m pytest -q`

#### Risco / pendência / dúvida

- Não houve refactor estrutural do `Runtime`.
- `Runtime` e `AgentRuntime` continuam coexistindo e grandes.

### 6. `session_state` / modos / pending decision

#### Implementado

- **Nenhuma mudança funcional** foi feita em `infer_session_state`, `compute_next_state`, `pending_decision`, `set_modes` ou vocabulário de estados.

#### Por que responde ao diagnóstico

- Não responde.

#### Validação

- Não aplicável.

#### Risco / pendência / dúvida

- Continua sendo uma área sensível e ainda não tratada.

### 7. Remoção de código morto

#### Implementado

- Remoção completa de `blender_addon/runtime/gn_targeting.py`.
- Remoção completa de `blender_addon/handler/_drafting_support.py`.
- Remoção do gate antigo de pós-falha em `feedback_evidence.py`.
- Limpeza de exports privados redundantes em `feedback.py`.
- Remoção de DIAG prints e helper `_diag` virou no-op.

#### Arquivos e funções

- `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\blender_addon\handler\feedback_evidence.py`
  - removidos `_POST_FAILURE_REQUIRED_SECTIONS`
  - `_post_failure_missing_sections`
  - `_post_failure_contract_status`
- `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\blender_addon\handler\feedback.py`
  - `__all__` reduzido
- `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\blender_addon\__init__.py`
  - remoção de prints DIAG em `_on_blend_load_post`
- `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\blender_addon\session\store.py`
  - `_diag` virou no-op
- `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\blender_addon\session\__init__.py`
  - docstring atualizada para refletir uso progressivo do v1

#### Por que responde ao diagnóstico

- Endereça vários pontos de limpeza P2/P3 descritos no diagnóstico.

#### Validação

- Validado por suíte completa:
  - `python -m pytest -q`

#### Risco / pendência / dúvida

- A remoção foi local e segura pelos testes, mas sem smoke real de addon Blender.

### 8. Documentação atualizada

#### Implementado

- Inserido aviso explícito em `CLAUDE.md` de que a árvore detalhada abaixo está desatualizada para o slim refactor e quais diretórios são a superfície viva atual.
- Criado este handoff técnico:
  - `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\docs\refactor_handoff\SLIM_DIAGNOSIS_IMPLEMENTATION_HANDOFF.md`

#### Arquivos

- `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\CLAUDE.md`
- `C:\Users\Eduardo\Desktop\blend_IA_ort_v2\docs\refactor_handoff\SLIM_DIAGNOSIS_IMPLEMENTATION_HANDOFF.md`

#### Por que responde ao diagnóstico

- Responde parcialmente ao ponto de documentação desatualizada.
- Não reescreve a estrutura toda, mas reduz o risco de alguém abrir caminhos mortos como referência primária.

#### Validação

- Não validado além de revisão textual/local.

#### Risco / pendência / dúvida

- `CLAUDE.md` continua com árvore detalhada antiga abaixo do aviso.

### 9. Testes adicionados ou corrigidos

#### Adicionados

- `tests/test_foundation_stabilization.py::test_refresh_baseline_uses_structural_memory_payload_instead_of_result_envelope`
- `tests/test_dispatch_smoke.py::test_inquiry_handler_uses_single_structural_read_when_refresh_is_needed`
- `tests/test_dispatch_smoke.py::test_legacy_drafting_support_module_is_removed`

#### Corrigidos / migrados

- `tests/test_draft_workspace_minimal_flow.py`
  - passou a chamar `workspace.handle` via helper local
- `tests/test_foundation_stabilization.py`
  - múltiplos testes migrados do shim antigo para `workspace.handle`
  - múltiplos imports trocados do shim para módulos reais

#### Validação executada na sessão original desta seção

- `python -m pytest -q`
  - em momentos intermediários: `175 passed`, `177 passed`, `178 passed`
  - estado final daquela etapa, após remoção total do shim: `177 passed in 0.43s`

#### Risco / pendência / dúvida

- Ainda falta um teste end-to-end cobrindo `AgentRuntime.run_turn` chamando `workspace.handle`.

## O que ainda NÃO foi feito do diagnóstico original

- Não houve convergência estrutural entre `Runtime` e `AgentRuntime`.
- Não houve emagrecimento grande de `blender_addon/runtime/core.py`.
- Não houve simplificação de `set_modes` nem remoção do legado de approval/control_owner.
- Não houve tratamento das múltiplas fontes de verdade para `session_state`.
- Não houve refactor de `pending_decision` para parar de escrever `session_state` inline.
- Não houve divisão real de `tools/handlers.py` em `reads.py`, `draft.py`, `capture.py`, `query.py`.
- Não houve divisão real de `tools/server_dispatch.py`.
- Não houve remoção dos handlers `apply_renames`, `apply_collections`, `apply_gn_edits` nem checagem externa do impacto.
- Não houve atualização estrutural completa de `CLAUDE.md`; só um aviso no topo da seção.
- Não houve adição de indicador visual de pending decision no painel.
- Não houve revisão do vocabulário `active/paused/no_session` vs `SESSION_STATES`.
- Não houve teste end-to-end do pipeline via `AgentRuntime.run_turn`.

## Possíveis regressões / pontos para revisar com cuidado

- `workspace.py` ficou maior ao absorver os dois helpers finais do draft; isso resolve surface, mas pode mascarar a próxima necessidade de extrair responsabilidades com cuidado.
- A remoção de `_drafting_support.py` foi coberta pela suíte, mas vale revisar qualquer automação externa não coberta por testes que ainda importe esse módulo.
- `tools/blender_runtime_validation.py` foi atualizado, mas não executado manualmente.
- A remoção de canonical GN targeting elimina código morto, mas vale revisar se havia alguma expectativa informal/futura no journal sobre `canonical_target_deviation`.
- O ajuste em `_handle_inquiry` reduz uma leitura estrutural, mas merece smoke manual em Blender para perguntas factuais com structural memory fresca e ausente.

## Próximos passos recomendados

### Onda 1: correções de risco funcional

- Adicionar um teste end-to-end mínimo via `AgentRuntime.run_turn` confirmando que o caminho de produção chega a `workspace.handle`.
- Fazer smoke manual do fluxo factual/inquiry no Blender para validar o comportamento após a remoção do refresh redundante.
- Executar `tools/blender_runtime_validation.py` manualmente, porque os imports foram corrigidos mas o script não foi exercitado.

### Onda 2: alinhamento de testes com produção

- Reduzir os helpers `_handle_draft_workspace_direct` dos testes, centralizando a preparação mínima comum.
- Adicionar cobertura explícita para `goal_mode` vindo do runtime real em vez de helpers de teste.

### Onda 3: limpeza de tools

- Mover implementações de leitura para `blender_addon/tools/reads.py`.
- Mover implementações de draft para `blender_addon/tools/draft.py`.
- Considerar `capture.py` e `query.py` para fatiar `tools/handlers.py`.
- Só depois revisar remoção de `apply_*`, confirmando se não existe uso externo relevante.

### Onda 4: limpeza de runtime/estado

- Escolher estratégia para `Runtime` vs `AgentRuntime` sem reescrever tudo:
  - ou `Runtime` vira bridge fina
  - ou mais responsabilidades sobem/descem de modo explícito
- Reduzir `set_modes` ao subset vivo.
- Tratar `session_state` como fonte única, removendo writes paralelos em `pending_decision` e caminhos legados.

### Onda 5: documentação e remoção final de legado

- Atualizar a seção de estrutura de arquivos em `CLAUDE.md` de forma real, não só com aviso.
- Revisar documentos que ainda mencionem `_drafting_support.py` ou caminhos antigos como se fossem ativos.
- Fazer último passe de grep por imports/caminhos legados.

## BLOCO DE HANDOFF

## Atualização de continuidade — 2026-05-09

### Onda 1 concluída/validada nesta continuação

- Adicionado teste end-to-end mínimo via `AgentRuntime.run_turn` confirmando que o caminho real de produção chega a `workspace.handle`.
- `tools/blender_runtime_validation.py` foi corrigido para não depender de `TurnRouter` removido e para falhar com exit non-zero quando contratos críticos quebram.
- O smoke real do Blender foi executado com:
  - `C:\Program Files\Blender Foundation\Blender 5.1\blender.exe --background --python tools\blender_runtime_validation.py`
- O script agora reporta `ok` e `validation_failures`.
- Último smoke real validado:
  - `runtime/validation/blender_runtime_validation_1778335109.json`
  - `ok: true`
  - `validation_failures: []`

### Bug encontrado e corrigido pela validação Blender

- O smoke factual/inquiry mostrou que `_maybe_run_discovery` fazia uma única leitura estrutural real, mas não atualizava `baseline_workspace`.
- Corrigido `blender_addon/handler/workspace.py:_maybe_run_discovery` para reaproveitar o payload de `build_tree_structural_memory` e chamar `_refresh_baseline_from_structural_memory(ctx, result)` sem adicionar segunda leitura.
- Validado pelo smoke Blender real:
  - uma chamada a `build_tree_structural_memory`;
  - prompt contém `ORTHOSIS_CONTEXT` e `ORTHOSIS_AGENT_VALIDATION`;
  - `baseline_workspace` recebe summary;
  - `validation_failures: []`.

### Onda 2 iniciada

- Criado `tests/draft_workspace_helpers.py` com `handle_draft_workspace_via_live_handler`.
- Removidas as duas cópias locais de `_handle_draft_workspace_direct` dos testes.
- Testes de Draft Workspace continuam passando pelo handler vivo `workspace.handle(ctx, goal_mode)`.

### Onda 3 iniciada

- `RuntimeDispatcher` passou a chamar `blender_addon.tools.draft` para:
  - `write_script_draft`;
  - `read_script_draft`.
- `RuntimeDispatcher` passou a chamar `blender_addon.tools.reads` para focal reads:
  - `get_node_context`;
  - `get_selected_nodes_context`;
  - `get_active_frame_context`;
  - `get_local_subgraph_context`;
  - `list_tree_nodes`;
  - `find_tree_nodes`.
- Adicionados smokes em `tests/test_dispatch_smoke.py` para travar essas rotas.
- Primeira fatia real movida de `tools/handlers.py` para `tools/draft.py`:
  - `_DRAFT_MIN_LINES`;
  - `_DRAFT_MIN_CHARS`;
  - `_is_placeholder_draft`;
  - `_infer_draft_revision_validity`;
  - `_draft_revision_reject_reason`.
- Segunda fatia real movida de `tools/handlers.py` para `tools/draft.py`:
  - `_attribute_chain`;
  - `_is_nodes_expr`;
  - `_has_geometry_nodes_operations`;
  - `_extract_referenced_node_names`.
- Terceira fatia real movida de `tools/handlers.py` para `tools/draft.py`:
  - `_semantic_text`;
  - `_semantic_compact`;
  - `_coerce_str_list`;
  - `_text_block_str_list`;
  - `_text_block_json_dict`;
  - `_semantic_term_present`;
  - `_matched_semantic_terms`;
  - `_draft_semantic_regression_reason`;
  - `_is_generic_focus_region`.
- Quarta fatia real movida de `tools/handlers.py` para `tools/draft.py`:
  - `_DRAFT_REVISION_RE`;
  - `_iter_text_blocks`;
  - `_draft_revision_blocks`;
  - `_draft_block_version`;
  - `_draft_revision_validity`;
  - `_latest_draft_block`;
  - `_best_draft_reasoning_block`;
  - `_draft_payload_from_block`;
  - `handle_read_script_draft`.
- Quinta fatia preparatória real movida de `tools/handlers.py` para `tools/draft.py`:
  - `_draft_domain_reject_reason`;
  - `_safe_draft_filename_part`;
  - `_archive_script_draft`.
- Sexta fatia real movida de `tools/handlers.py` para `tools/draft.py`:
  - `handle_write_script_draft`.
- Micro-limpeza de compatibilidade após grep local:
  - o teste que importava `_extract_referenced_node_names` e `_has_geometry_nodes_operations` via `tools.handlers` passou a importar de `tools.draft`;
  - `tools/handlers.py` agora mantém aliases/imports de compatibilidade apenas para `handle_write_script_draft` e `handle_read_script_draft`;
  - `HANDLERS` continua expondo `write_script_draft` e `read_script_draft` pelo caminho antigo usado por `server.py`.
- Sétima fatia real movida de `tools/handlers.py` para um módulo próprio:
  - criado `blender_addon/tools/query.py`;
  - movido `handle_query_node_types` para `tools.query`;
  - `RuntimeDispatcher` passou a chamar `tools.query.handle_query_node_types`;
  - `tools.handlers` mantém alias/import de compatibilidade e `HANDLERS["query_node_types"]`.
- Adicionado smoke em `tests/test_dispatch_smoke.py` para travar a rota `query_node_types -> tools.query`.
- Oitava fatia real movida de `tools/handlers.py` para um módulo próprio:
  - criado `blender_addon/tools/execution.py`;
  - movido `handle_execute_code` para `tools.execution`;
  - `RuntimeDispatcher` passou a chamar `tools.execution.handle_execute_code` tanto em `execute_code` quanto no caminho interno de screenshot;
  - `tools.handlers` mantém alias/import de compatibilidade e `HANDLERS["execute_code"]`.
- Adicionado smoke em `tests/test_dispatch_smoke.py` para travar a rota `execute_code -> tools.execution`.
- Nona fatia real movida de `tools/handlers.py` para um módulo próprio:
  - criado `blender_addon/tools/edits.py`;
  - movidos `handle_apply_renames`, `handle_apply_collections`, `handle_apply_gn_edits`, `_execute_gn_operation` e `_find_socket`;
  - `tools.handlers` mantém aliases/imports de compatibilidade e `HANDLERS` segue expondo `apply_renames`, `apply_collections` e `apply_gn_edits`.
- Adicionado smoke em `tests/test_dispatch_smoke.py` para travar a façade legacy `HANDLERS -> tools.edits`.
- Décima fatia real movida de `tools/handlers.py` para um módulo próprio:
  - criado `blender_addon/tools/snapshots.py`;
  - movidos os wrappers `handle_capture_scene`, `handle_capture_node_trees` e `handle_capture_full`;
  - `RuntimeDispatcher` passou a usar `tools.snapshots` nos helpers internos `_capture_scene`, `_capture_node_trees` e `_capture_full`;
  - `tools.handlers` mantém aliases/imports de compatibilidade e `HANDLERS` segue expondo `capture_scene`, `capture_node_trees` e `capture_full`.
- Adicionado smoke em `tests/test_dispatch_smoke.py` para travar a rota interna de snapshots do dispatcher.
- Décima primeira fatia real movida para `tools.reads`:
  - `tools.reads` deixou de ser reexport e passou a conter os handlers reais de reads focais e reads diretos;
  - movidos `handle_get_node_context`, `handle_get_selected_nodes_context`, `handle_get_active_frame_context`, `handle_get_local_subgraph_context`, `handle_list_tree_nodes`, `handle_find_tree_nodes`, `_expand_node_neighborhood` e `_serialize_nodes_and_links`;
  - `tools.handlers` mantém aliases/imports de compatibilidade e `HANDLERS` segue expondo todos os reads;
  - `RuntimeDispatcher` já chamava `tools.reads`, então a rota de produção ficou alinhada ao módulo real.

### Validação atual desta continuação

- `python -m py_compile blender_addon/tools/draft.py blender_addon/tools/handlers.py blender_addon/tools/reads.py blender_addon/tools/edits.py blender_addon/tools/execution.py blender_addon/tools/query.py blender_addon/tools/snapshots.py blender_addon/tools/server_dispatch.py`
- `python -m pytest tests/test_dispatch_smoke.py -q`
  - `16 passed`
- `python -m pytest -q`
  - `184 passed in 0.69s`
- Blender real:
  - relatório mais recente: `runtime/validation/blender_runtime_validation_1778339841.json`
  - `ok: true`
  - `validation_failures: []`
- Observação: durante a movimentação do writer houve uma falha intermitente uma vez no teste `test_write_script_draft_archives_full_revision_to_disk` dentro da suíte completa; o teste isolado, o arquivo afetado inteiro, o prefixo de arquivos relevante e a suíte completa repetida passaram depois, sem mudança adicional.

### Ponto de retomada

Use este bloco para iniciar a próxima sessão sem reler todo o histórico.

- Working tree intencionalmente sujo, sem branch nova e sem commit.
- Último estado validado: `184 passed`, smoke Blender real `ok: true`.
- Onda 3 de `tools/handlers.py` está funcionalmente encerrada.
- `tools/handlers.py` agora é uma façade fina: `execute_in_main_thread` + `HANDLERS`.
- A superfície real de tools ficou distribuída em:
  - `blender_addon/tools/draft.py`
  - `blender_addon/tools/reads.py`
  - `blender_addon/tools/edits.py`
  - `blender_addon/tools/execution.py`
  - `blender_addon/tools/query.py`
  - `blender_addon/tools/snapshots.py`
- Não remover `tools.handlers.HANDLERS` ainda; `blender_addon/server.py` e possíveis integrações externas ainda usam essa façade.

### Próximo passo recomendado a partir daqui

Próxima frente: `session_state` / `pending_decision`, não mais `tools/handlers.py`.

Primeira onda recomendada:

1. Fazer inventário por grep, sem editar:
   - `rg -n "session_state|pending_decision|set_pending_decision|compute_next_state|infer_session_state|set_modes|control_owner|approval" blender_addon tests docs`
2. Comparar com `docs/state_inventory.md`, especialmente as seções de `runtime/session_state`, `ExecutionState.session_state` e `PendingUserDecision`.
3. Escolher a menor consolidação validável. Preferência atual:
   - não mexer em router amplo;
   - não reescrever FSM;
   - procurar um write paralelo ou campo espelhado claramente redundante;
   - adicionar ou ajustar teste antes de remover comportamento.
4. Validar com:
   - testes focados de `tests/test_pending_user_decision.py`, `tests/test_routing_observability.py`, `tests/test_repair_conversation_loop.py`;
   - `python -m pytest -q`;
   - smoke Blender real se tocar runtime/handler de produção.

### Pendências ainda abertas

- `Runtime` e `AgentRuntime` continuam coexistindo e grandes.
- `session_state`, `pending_decision`, `set_modes` e legado de approval/control_owner ainda não foram simplificados.
- `server_dispatch.py` continua grande, mas a extração de `tools/handlers.py` reduziu a superfície de risco imediata.
- `CLAUDE.md` ainda é majoritariamente histórico; o topo aponta para este handoff como referência de retomada.

### Regras para a próxima sessão

- Não criar branch.
- Não fazer commit.
- Não reescrever do zero.
- Continuar por refatorações cirúrgicas, incrementais e validáveis.
- Não inventar conclusão sem validação.
- Sempre alinhar testes ao caminho real de produção.
- Se houver dúvida entre duas frentes grandes, priorizar a menor e de menor risco funcional.
