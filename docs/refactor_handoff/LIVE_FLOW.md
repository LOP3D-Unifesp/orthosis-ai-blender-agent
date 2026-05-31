# LIVE_FLOW.md — Fluxo vivo do addon (atualizado 2026-05-31)

> Fonte de verdade para a estrutura atual pós-slim-refactor (branch `slim-refactor` mergeada em `master`).
> Atualizar aqui antes de atualizar CLAUDE.md.
> Estado validado: `python -m pytest -q` → **185 passed** (1.2s); smoke Blender `ok: true`.

---

## 1. Fluxo completo: usuário digita → resposta no painel

```
ui/panel_chat_turn.py  _send_user_message()          [thread principal Blender]
  └─ lança thread background
        ↓
  _run_chat_turn()
    1. Adiciona mensagem user ao SESSION + chat JSONL (chat_store.append)
    2. Chama runtime.run_turn(message, blend_path, ...)
        ↓
core/runtime.py  AgentRuntime.run_turn()
    3. Carrega V1 session via runtime/core.py Runtime.v1_session_for(blend_path)
    4. Reset por turno (pending_draft_action, phase guard)
    5. Resolve pending_decision se houver (pending_decision.py resolve_pending_decision)
    6. Tenta fast_path — fast_path.py try_fast_path()
       ├─ FP4: draft_confirmation  (pending draft sem LLM)
       ├─ FP1: greetings           (respostas fixas)
       ├─ FP2: help/capability     (texto estático)
       ├─ FP2b: blender_console    (onde ficam os prints)
       └─ FP3: simple reads        (get_node_context direto)
       Se hit → retorna imediatamente (sem LLM)
    7. Se nenhum fast path: infer_turn_intent() → (turn_class, goal_mode)
       ├─ runtime/router.py  infer_turn_intent()
       │   Regra 1: pending_decision respondida → DRAFT_WORKSPACE / focal_correction
       │   Regra 2: prefixo [RESULTADO DE EXECUÇÃO] → EXECUTION_FEEDBACK
       │   Regra 3: padrões de diagnóstico+retry → DRAFT_WORKSPACE / focal_correction
       │   Regra 4: imperativos de escrita → DRAFT_WORKSPACE / focal_correction
       │   Default: CONTEXT_INQUIRY / inquiry
    8. Routing observability log (routing_obs.py — loga journal; também fornece infer_session_state/compute_shadow_handler usados no handler)
    9. handler/workspace.py  workspace.handle(ctx, goal_mode)
        ↓
handler/workspace.py  handle(ctx, goal_mode)
   10. Seleciona GoalConfig para o goal_mode
   11. Carrega estado do pipeline (_load_draft_workspace_state)
   12. Lê draft atual se relevante
   13. Executa _handle_inquiry ou _handle_draft_goal
       ├─ inquiry/diagnose_only → leituras focais, sem write_script_draft
       └─ focal_correction/functional_expansion/feedback_fix
              → _maybe_run_discovery, _refresh_baseline
              → ctx.call_agent_loop(system_prompt, tools)
                    ↓
core/agent_loop.py  agent_loop()
   14. Loop Claude API (request_with_retry / stream_with_retry)
       → tool_use_block → dispatch_tool_raw() → tools/client.py call_blender_socket()
                    ↓ TCP localhost:65432
       blender_addon/server.py  runtime_tool_call
         → tools/server_dispatch.py  RuntimeDispatcher.execute()
           → tools/draft.py, reads.py, edits.py, execution.py, query.py, etc.
   15. Termina em texto final ou round-limit com finalizador
        ↓
core/runtime.py (continuação)
   16. _finalize_turn(): adiciona mensagem assistant ao histórico
   17. chat_store.append() + fsync (JSONL)
   18. store.save() (V1 session JSON, atomic write)
   19. Retorna response_text
        ↓
ui/panel_chat_turn.py
   20. SESSION.messages.append(response)
   21. SESSION.running = False  → timer de redraw detecta e atualiza painel
```

---

## 2. Arquivos centrais (live core — não tocar sem razão forte)

| Arquivo | Papel | Linhas (wc -l) |
|---|---|---|
| `blender_addon/core/runtime.py` | Orquestrador de turno: fast_path, infer_turn_intent, workspace.handle, persist | ~1908 ⚠️ |
| `blender_addon/handler/workspace.py` | Handler unificado: GoalConfig, inquiry, draft, feedback | ~807 |
| `blender_addon/runtime/router.py` | `infer_turn_intent` — 4 regras estruturais | ~178 |
| `blender_addon/fast_path.py` | Curto-circuito sem LLM: greetings, help, reads, draft_confirmation | ~392 |
| `blender_addon/runtime/core.py` | Runtime Blender-side: session manager, dispatcher bridge | ~1274 ⚠️ |
| `blender_addon/session/schema.py` | `Session`, `ExecutionState`, `PendingUserDecision`, `SESSION_STATES` | ~986 |
| `blender_addon/session/store.py` | `SessionV1Store`: JSON atômico, quarantine | ~683 |
| `blender_addon/session/chat_store.py` | `ChatHistoryStore`: JSONL append-only, fsync | ~120 |
| `blender_addon/tools/server_dispatch.py` | Dispatcher Blender-side das ferramentas (~1843L — candidato a cortes) | ~1843 ⚠️ |
| `blender_addon/tools/handlers.py` | Façade HANDLERS para server.py (manter até server.py migrar) | ~50 |
| `blender_addon/server.py` | TCP bridge Blender porta 65432 | ~262 |
| `blender_addon/ui/panel_chat_turn.py` | Entry point do usuário + thread de turno | ~175 |
| `blender_addon/ui/cycle_operators.py` | Operadores do ciclo: execute, run, revert, report_result | ~306 |
| `blender_addon/runtime/pending_decision.py` | `set_pending_decision`, `resolve_pending_decision`, `_match_option` | ~331 |
| `blender_addon/text_utils.py` | Helpers NLP compartilhados: `_message_words`, `_has_prefix`, `_has_phrase` | ~60 |

> ⚠️ `core/runtime.py` (~1908L) e `runtime/core.py` (~1274L) são os dois maiores arquivos do núcleo; ambos são candidatos à convergência na Phase 3 do slim plan. `server_dispatch.py` (~1843L) continua grande — extração incremental em andamento.

### Helpers de handler (live, mas focados)

| Arquivo | Papel |
|---|---|
| `blender_addon/handler/draft_context.py` | `_tree_render_block`, `_refresh_baseline_from_structural_memory` |
| `blender_addon/handler/draft_finalize.py` | Logs e diagnósticos pós-draft |
| `blender_addon/handler/draft_policy.py` | `_draft_workspace_tool_policy` |
| `blender_addon/handler/draft_prompt.py` | `_build_draft_workspace_system` |
| `blender_addon/handler/draft_response.py` | Parse de resposta, extração de code fences |
| `blender_addon/handler/draft_runtime.py` | `_with_draft_streaming_disabled`, `_replace_last_assistant_message` |
| `blender_addon/handler/draft_state.py` | `DraftWorkspacePipelineState`, `_load_draft_workspace_state` |
| `blender_addon/handler/feedback.py` | Handler de execution feedback |
| `blender_addon/handler/feedback_classifier.py` | `_classify_execution_feedback`, `_is_execution_diagnosis_request` |
| `blender_addon/handler/feedback_evidence.py` | Evidência estática pós-falha (nós tocados, conflitos) |
| `blender_addon/handler/prompt.py` | Prompt helpers genéricos |

### Tools Blender-side (live)

| Arquivo | Ferramentas |
|---|---|
| `blender_addon/tools/draft.py` | `write_script_draft`, `read_script_draft` |
| `blender_addon/tools/reads.py` | `get_node_context`, `list_tree_nodes`, `find_tree_nodes`, etc. |
| `blender_addon/tools/edits.py` | `apply_renames`, `apply_collections`, `apply_gn_edits` |
| `blender_addon/tools/execution.py` | `execute_code` (user-triggered only) |
| `blender_addon/tools/query.py` | `query_node_types` (local, zero API cost) |
| `blender_addon/tools/snapshots.py` | `capture_scene`, `capture_node_trees`, `capture_full` |
| `blender_addon/tools/structural.py` | `build_tree_structural_memory` |
| `blender_addon/tools/tree_analysis.py` | Helpers de análise pura extraídos do dispatcher |

---

## 3. Arquivos removidos/depreciados (NÃO recriar)

| Arquivo | Status | Removido em |
|---|---|---|
| `blender_addon/agent_runtime.py` | **Deletado** — substituído por `core/runtime.py` | slim-refactor Fase 1 |
| `blender_addon/runtime_dispatch.py` | **Deletado** — substituído por `tools/server_dispatch.py` | slim-refactor |
| `blender_addon/handlers.py` | **Deletado** — substituído por `tools/handlers.py` (façade) | slim-refactor |
| `blender_addon/skill_router.py` | **Deletado** | slim-refactor |
| `blender_addon/runtime_agent_loop.py` | **Deletado** — substituído por `core/agent_loop.py` | slim-refactor |
| `blender_addon/runtime/handlers/drafting.py` | **Deletado** (bulk) — funcionalidade em `handler/` | slim-refactor Fase 4 |
| `blender_addon/runtime/handlers/workspace.py` (antigo) | **Deletado** — substituído por `handler/workspace.py` | slim-refactor |
| `blender_addon/runtime/handlers/_agent_loop.py` | **Deletado** | slim-refactor |
| `blender_addon/runtime/handlers/greeting.py` | **Deletado** | slim-refactor |
| `blender_addon/runtime/state_machine.py` | **Deletado** | slim-refactor Fase 1 |
| `blender_addon/runtime/gn_targeting.py` | **Deletado** | slim-refactor |
| `blender_addon/runtime/staged_payload.py` | **Deletado** | slim-refactor |
| `blender_addon/tools.py` (raiz) | **Deletado** — substituído por `tools/` | slim-refactor |

### Módulos removidos adicionalmente (não constam na tabela acima)

| Arquivo | Status |
|---|---|
| `blender_addon/knowledge_updater.py` | **Deletado** — não está rastreado no git. Consequência: `knowledge/domain/learned_patterns.md` ficou órfão (existe, retriever carrega, mas está estático — 1 padrão). |
| `blender_addon/simulator_mapper.py` | **Deletado** — não está rastreado no git. |

### Módulos congelados (existem mas não evoluir)

| Arquivo | Motivo |
|---|---|
| `blender_addon/runtime/routing_obs.py` | **Parcialmente live.** Exporta `infer_session_state` (importado em `handler/workspace.py:216`) e `compute_shadow_handler` (importado em `core/runtime.py:558`). Também loga `routing_observation` no journal (observabilidade). Não é shadow-only — remover requer redirecionar os dois imports. |

---

## 4. Testes relevantes

> **Atenção:** a lista abaixo reflete os testes **realmente rastreados** pelo git (verificado em 2026-05-31 — `git ls-files tests/`). Os itens marcados com `⬜ ausente` são cobertura desejável ainda não criada.

```
tests/                                                            STATUS
├── draft_workspace_helpers.py         ← helpers de fixture compartilhados   ✅ existe
├── test_dispatch_smoke.py             ← smoke de dispatch de ferramentas     ✅ existe
├── test_draft_confirmation_fp4.py     ← fast path FP4 (confirmação de draft) ✅ existe
├── test_draft_workspace_minimal_flow.py ← fluxo mínimo do workspace         ✅ existe
├── test_foundation_stabilization.py  ← clear_runtime_context, persist       ✅ existe (3319L)
├── test_pending_user_decision.py      ← resolve_pending_decision, _match_option ✅ existe
├── test_repair_conversation_loop.py   ← loop de reparo pós-falha             ✅ existe
├── test_routing_observability.py      ← routing_obs shadow mode             ✅ existe
├── test_session_persistence_durability.py ← reopen deferido, fsync          ✅ existe
├── test_session_store_explicit_legacy_import.py ← import legacy explícito   ✅ existe
└── test_session_store_isolation.py    ← SessionV1Store isolation             ✅ existe

Cobertura desejável ainda ausente:
├── test_text_utils.py                 ← _message_words, _has_prefix, _has_phrase ⬜ ausente
├── test_fast_path.py                  ← fast paths FP1–FP3                  ⬜ ausente
├── test_router.py                     ← infer_turn_intent (4 regras)        ⬜ ausente
├── test_workspace.py                  ← workspace.handle, GoalConfig        ⬜ ausente
├── test_feedback_classifier.py        ← _classify_execution_feedback        ⬜ ausente
├── test_feedback_evidence.py          ← evidência estática pós-falha        ⬜ ausente
├── test_session_schema.py             ← Session, ExecutionState             ⬜ ausente
├── test_session_store.py              ← SessionV1Store (atomic write)       ⬜ ausente
└── test_chat_store.py                 ← ChatHistoryStore (append, fsync)    ⬜ ausente
```

Rodar: `python -m pytest -q` na raiz do projeto → **185 passed** (1.2s, sem Blender).

---

## 5. Pendências conhecidas

### Phase 3: convergência de runtimes (maior risco)

`AgentRuntime` (`core/runtime.py`) e `Runtime` (`runtime/core.py`) coexistem. O `AgentRuntime` é o orquestrador Python-side (faz chamadas à API Anthropic). O `Runtime` é o Blender-side (gerencia sessão, despacha ferramentas via socket). A convergência completa (Phase 3 do slim plan) ainda está pendente — os dois módulos têm papéis distintos e não podem ser simplesmente fundidos sem validação smoke no Blender.

### `tools/server_dispatch.py` (~1754L)

Ainda grande. `tree_analysis.py` foi extraído na sessão 2026-05-13. Candidato a mais cortes quando houver smoke completo que confirme que os helpers restantes são todos utilizados.

### `PendingUserDecision` — Wave 5.C

`resolve_pending_decision` existe e funciona para ordens explícitas. A resolução por referência ao nome da opção ("Caminho B", "Opção A") pode produzir falsos negativos se o vocabulário não bater exatamente. A cobertura de testes cobre os casos documentados; edge cases de linguagem natural permanecem.

### `EXECUTION_FEEDBACK` path

O handler de execution feedback ainda corre por `handler/feedback.py` separado do workspace unificado. Funciona, mas a consolidação final (absorver no workspace como `feedback_fix` goal_mode) está pendente.

### CLAUDE.md

A seção "Estrutura de arquivos" tem o preamble atualizado apontando para este documento, mas a árvore de diretórios detalhada abaixo ainda reflete o estado pré-slim por questões históricas. A reescrita completa está prevista para a Fase 7 (pós-merge em main).

---

## 6. Próximos cortes recomendados (por ordem de risco/impacto)

### Baixo risco — pode fazer em qualquer sessão

1. **`blender_addon/runtime/routing_obs.py` — consolidar, não remover diretamente**
   Exporta duas funções live (`infer_session_state` em `handler/workspace.py:216`, `compute_shadow_handler` em `core/runtime.py:558`) além do logging de observabilidade. Não é candidato à remoção sem antes mover essas funções para `runtime/router.py` ou `runtime/state_ops.py` e atualizar os imports.

2. **`blender_addon/tools/server_dispatch.py` — continuar extração de helpers puros**
   Padrão já validado com `tree_analysis.py`. Identificar próximo cluster de funções puras (ex: helpers de snapshot, helpers de interface) e extrair para módulos focados. Testar com `pytest -q` após cada extração.

3. **`blender_addon/knowledge_updater.py` — deletar ou documentar decisão de reativar**
   Congelado por design. Se não há plano de reativar, deletar evita confusão. Se há plano, documentar o trigger (quando `execute_code` voltará a ser rastreado).

### Médio risco — requer smoke no Blender antes de commitar

4. **`blender_addon/handler/feedback.py` — absorver no workspace como `feedback_fix`**
   Completaria a unificação iniciada na Onda 4c. O roteador já emite `EXECUTION_FEEDBACK` → o workspace poderia tratar como `feedback_fix` goal_mode em vez de desviar para handler separado.

5. **`blender_addon/runtime/core.py` — clarificar superfície pública**
   `Runtime.v1_session_for()` é o método principal consumido pelo `AgentRuntime`. Documentar explicitamente o contrato e os outros métodos que são internos/legado.

### Alto risco — só pós-Phase 3 convergence

6. **Convergência `AgentRuntime` + `Runtime`**
   O maior item pendente do slim plan. Requer mapeamento cuidadoso de quem chama o quê, porque os dois têm ciclos de vida diferentes (Python-side vs. Blender main thread).
