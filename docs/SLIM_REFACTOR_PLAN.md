# Slim Refactor Plan

> Note for `codex/biomodel-source-migration`: this is historical context, not the governing plan for the biomodel-source branch. Any statement here that treats `GN_Agent_Draft` as the product source of truth applies only to the legacy draft-mutation workflow. The governing biomodel decision is `docs/BIOMODEL_SOURCE_MODE_DECISION.md`.

> Documento único de execução desta branch (`slim-refactor`).
> Criado em 2026-05-06.
> Objetivo: substituir o miolo bloated do addon (~10k linhas em 4 arquivos) por um núcleo enxuto (~1.5–2k linhas) preservando os módulos que comprovadamente funcionam.
> **Esta branch existe para isso e nada mais.** Quando o plano fechar, vira PR único contra `master`.

---

## 0. Princípio

**Não recomeçar do zero. Cirurgia direcionada.**

A ideia central do produto está certa: agente lê árvore GN → escreve script Python → designer executa manualmente → reporta resultado → itera. O que cresceu demais foi a **infraestrutura de gerenciamento de turno**, não o domínio.

Os 6 documentos em `docs/` (atlas, draft flow, decision matrix, state inventory, repair loop, refactor plan) já fizeram a auditoria. Este plano usa as conclusões deles, não as refaz.

---

## 1. O que **NÃO** vamos tocar

Estes módulos funcionam, foram validados, e custariam bugs reais se reescritos. Ficam intactos:

| Módulo | Por quê |
|---|---|
| `blender_addon/server.py` | Socket bridge TCP 65432, estável |
| `blender_addon/capture.py` | Snapshot da cena/node trees, captura `socket.identifier` corretamente |
| `blender_addon/safety_policy.py` | Pequeno, central, correto |
| `blender_addon/session/schema.py` | V1 dataclass, fonte estruturada |
| `blender_addon/session/store.py` | Per-file V1 com quarentena e atomic write |
| `blender_addon/session/chat_store.py` | JSONL append-only com fsync |
| `blender_addon/session/baseline.py` | `BaselineWorkspace` + `compute_tree_signature` |
| `blender_addon/operation_journal.py` | Journal por run, indispensável p/ debug |
| `blender_addon/snapshot_manager.py` | Snapshot do `.blend` antes da execução manual |
| `blender_addon/ui/chat_session.py` | Singleton `SESSION` testável, sanitiza código |
| `blender_addon/ui/screenshot.py` | Captura via PowerShell + .NET |
| `blender_addon/ui/_helpers.py` | Utilitários sem `bpy` |
| `blender_addon/runtime/tree_renderer.py` | Render compacto da árvore (Onda 4b) |
| `blender_addon/runtime/pending_decision.py` | Helper de `PendingUserDecision` |
| `blender_addon/knowledge/corpus.py` + `retriever.py` | Carrega/seleciona conhecimento por turn class |
| `knowledge/domain/*.md`, `knowledge/skills/*.md`, `knowledge/recipes/*.md` | Corpus de domínio (não código) |
| `contracts/*.json` | Schemas de referência |
| Text Editor `GN_Agent_Draft` como fonte de verdade do script | Invariante do produto |

---

## 2. O que **vai** ser reescrito

Os 4 arquivos bloated identificados pela auditoria + metade da UI:

| Arquivo atual | Linhas | Destino |
|---|---:|---|
| `blender_addon/agent_runtime.py` | 1857 | reescrito enxuto (~300 linhas) |
| `blender_addon/runtime_dispatch.py` | 2127 | dividido em 2 módulos focados |
| `blender_addon/runtime/handlers/drafting.py` | 2595 | reescrito enxuto (~400 linhas) |
| `blender_addon/handlers.py` | 1573 | dividido por família (~3 arquivos pequenos) |
| `blender_addon/ui/panel.py` | 1752 | dividido em painel + operadores (~600 + ~400) |
| **Total** | **~9.9k** | **~1.7k** |

---

## 3. O que **vai** ser deletado sem substituição

Catálogo de legado/morto identificado em `docs/architecture_atlas.md` §3 e `docs/refactor_decision_matrix.md` §6:

| Item | Motivo |
|---|---|
| `blender_addon/runtime/state_machine.py` | Cita `awaiting_confirmation` que nem existe mais em `EXECUTION_PHASES` |
| `blender_addon/runtime/handlers/_agent_loop.py` | Marcado `@deprecated` desde a Onda 4c |
| `blender_addon/runtime/handlers/drafting.handle_draft_workspace()` | Path órfão; `dispatch_turn` não chama mais |
| `blender_addon/runtime/handlers/workspace._delegate_legacy()` | Sem callers nos `GOAL_CONFIGS` atuais |
| `handlers.HANDLERS` legacy direct commands no socket | Path paralelo ao `runtime_tool_call`, sem uso real |
| `legacy/session_store.py` + `_sync_v1_to_legacy()` | Dual persistence; V1 já é fonte de verdade |
| `blender_addon/runtime_migration.py` | Migração one-shot de schema antigo |
| `blender_addon/skill_router.py` | Resquício; roteamento real é `runtime_dispatch` |
| `blender_addon/knowledge_updater.py` | Congelado por design (CLAUDE.md), depende de evento que não acontece |
| `blender_addon/simulator_mapper.py` | `apply_simulator_payload` bloqueado no fluxo automático |
| Ferramentas atômicas em `tools.py`/`handlers.py`: `create_node`, `connect_nodes`, `set_node_value`, `rename_object`, `move_to_collection`, `make_plan` | Bloqueadas no agente draft-first; nunca chamadas |
| Prints `_diag(...)` espalhados pelo código | Instrumentação temporária |
| `blender_addon/runtime/state_ops.py` flat state como fonte | Vira só um adapter interno (overlay V1), perde semântica própria |
| `ExecutionState.phase` (legado) — manter só `session_state` + `work_cycle_phase` | `state_inventory.md` §3: três conceitos sobrepostos |

Estimativa: mais ~3–4k linhas saindo só de deleções diretas.

---

## 4. Arquitetura-alvo (pós-refactor)

```
blender_addon/
├── __init__.py                     ← registro Blender, inalterado
├── server.py                       ← socket bridge, inalterado
├── capture.py                      ← snapshot cena/GN, inalterado
├── safety_policy.py                ← inalterado
├── operation_journal.py            ← inalterado
├── snapshot_manager.py             ← inalterado
├── model_policy.py                 ← inalterado
│
├── core/                           ← NOVO: orquestração de turno (substitui agent_runtime.py)
│   ├── runtime.py                  ← AgentRuntime enxuto (~300 linhas)
│   ├── agent_loop.py               ← loop tool-use Claude API (~200 linhas)
│   ├── tool_policy.py              ← contrato de draft + economy_retry (~150 linhas)
│   └── api_client.py               ← cliente Anthropic com retry (atual runtime_api_client.py, mantido)
│
├── handler/                        ← NOVO: 1 handler único, sem dispatcher por turn_class
│   ├── workspace.py                ← handler único: inquiry | diagnose | draft (~400 linhas)
│   ├── draft_policy.py             ← política de ferramentas + cobertura semântica do draft
│   ├── draft_response.py           ← formatação/sanitização de resposta do draft
│   ├── draft_state.py              ← leitura/sync de draft + modos de retry/escrita
│   ├── draft_finalize.py           ← inspeção de writes + motivos de não-escrita/regressão
│   ├── feedback.py                 ← feedback pós-execução: diagnóstico + pending decision
│   ├── feedback_evidence.py        ← leitura da revisão falha + evidência estática + fallback
│   └── prompt.py                   ← builder de system prompt (~200 linhas)
│
├── tools/                          ← NOVO: divisão de handlers.py + runtime_dispatch.py
│   ├── schemas.py                  ← TOOLS + AGENT_TOOLS (atual tools.py top, ~150 linhas)
│   ├── client.py                   ← dispatch_tool_raw via socket (atual tools.py bottom, ~100 linhas)
│   ├── reads.py                    ← get_node_context, find_tree_nodes, get_scene_summary, etc.
│   ├── draft.py                    ← write_script_draft + read_script_draft + validações
│   ├── structural.py               ← build_tree_structural_memory, prepare_draft_context
│   └── server_dispatch.py          ← RuntimeDispatcher enxuto (substitui runtime_dispatch.py)
│
├── session/                        ← preservado integralmente
│   ├── schema.py
│   ├── store.py
│   ├── chat_store.py
│   ├── baseline.py
│   ├── session_state_store.py
│   ├── pending_decision.py         ← movido para cá (era em runtime/)
│   └── history.py
│
├── runtime/                        ← preservado parcialmente
│   ├── tree_renderer.py            ← inalterado
│   ├── routing_obs.py              ← inalterado (auditoria sem dispatch)
│   └── (tudo mais sai)
│
├── knowledge/                      ← preservado
│   ├── corpus.py
│   └── retriever.py
│
└── ui/
    ├── panel.py                    ← reescrito enxuto: só draw() (~600 linhas)
    ├── operators.py                ← NOVO: todos os bpy.types.Operator (~400 linhas)
    ├── chat_session.py             ← inalterado
    ├── advanced.py                 ← inalterado
    ├── screenshot.py               ← inalterado
    └── _helpers.py                 ← inalterado
```

### Pipeline de turno (alvo)

```
ui/panel → operators._send_user_message
       ↓
core.runtime.run_turn(message)
       ↓
   load V1 session + chat history + pending_decision
       ↓
   resolve pending_decision (se houver) → goal_mode
       ↓ (se não)
   simple intent classification (sem regex bloated):
     - prefix [RESULTADO DE EXECUÇÃO] → feedback
     - has draft + imperative verb → focal_correction
     - default → inquiry
       ↓
   handler.workspace.handle(goal_mode, ctx)
       ↓
   core.agent_loop(system_prompt, tools, max_rounds)
       ↓ (tool calls)
   tools.client.dispatch_tool_raw → socket → tools.server_dispatch
       ↓
   save chat + V1 + journal
       ↓
   return response
```

Desaparecem: `TurnRouter`, `dispatch_turn`, `_workspace_goal_mode`, `state_machine.py`, fluxo `EXECUTION_FEEDBACK` separado, dois handlers paralelos (`drafting.handle_draft_workspace` + `workspace._handle_draft_goal`).

---

## 5. Invariantes preservadas (não-negociáveis)

Todas vieram de bug real custoso. Não tirar:

1. **Agente nunca executa script.** `execute_code` e `make_plan` ficam bloqueados; usuário roda manualmente no Text Editor.
2. **`GN_Agent_Draft` é fonte de verdade do script vivo.** Chat não recebe código.
3. **Falha de execução não autoriza reescrita automática.** Turno seguinte pós-falha precisa de aprovação explícita do designer.
4. **Snapshot do `.blend` antes de execução manual.** Sempre.
5. **Render compacto da árvore no system prompt** quando há `tree_structural_memory` fresca ou persistida.
6. **`focal_budget=3` mínimo em REPAIRING.** Bug real, run `0894ae38`.
7. **Chat persistido em JSONL antes do save V1.** `fsync()` explícito.
8. **`PendingUserDecision` resolve aprovação por estado, não por regex.** Wave 5.C entrega isso integrado no novo handler.
9. **`STRATEGY_PROPOSED` não colapsa para `REPAIRING` no mesmo run.** Guarda explícita.
10. **Quarentena de session JSON corrompido** em `runtime/sessions_v1/archive/quarantine/`.

---

## 6. Sequência de execução

Cada fase é um commit (ou pequeno conjunto de commits) na branch `slim-refactor`. Não pular ordem. Cada fase tem critério de saída antes da próxima.

### Fase 0 — Setup ✅ (já feita)

- [x] `git init`
- [x] `.gitignore` ajustado (`*.blend`, `*.blend1`, tmp dirs)
- [x] Commit baseline `master`
- [x] Branch `slim-refactor`
- [x] Este documento

**Critério:** branch criada, plano escrito, baseline preservada em `master`.

---

### Fase 1 — Deletar legado puro ✅ (2026-05-06)

**O que:** remover os módulos catalogados em §3 que não têm caller real. Sem reescrever nada — só apagar e ajustar imports quebrados.

Lista mínima:
- [x] `blender_addon/runtime/state_machine.py`
- [x] `blender_addon/runtime/handlers/_agent_loop.py` (funções vivas movidas para workspace.py antes da deleção)
- [x] `blender_addon/runtime_migration.py` (stubbed to no-op em store.py + operation_journal.py)
- [x] `blender_addon/skill_router.py` (inlined em tools/server_dispatch.py na Fase 2)
- [x] `blender_addon/knowledge_updater.py`
- [x] `blender_addon/simulator_mapper.py`
- [x] Diretório `legacy/` deletado
- [x] Schemas de ferramentas atômicas em `tools.py` (`make_plan`, `apply_simulator_payload`)
- [x] Handlers correspondentes em `handlers.py` (`_tool_apply_simulator_payload`)
- [x] `_sync_v1_to_legacy()` + chamadas removidas de `agent_runtime.py`
- [x] `import_legacy_sessions_explicit()` virou no-op em `session/store.py`
- [x] `_diag_audit.py`, `mock_prompt_capture.txt`, `test_journal.py` na raiz deletados
- [x] 3 testes atualizados para refletir comportamento no-op

**Commit:** `78ed193 chore(slim): delete dead modules and legacy paths`

**Critério de saída:**
- [x] 216 tests coletados, 2 falhas pré-existentes (inalteradas)
- [ ] Addon ainda carrega no Blender (smoke manual — pendente até Fase 6)
- [x] >4k linhas removidas

---

### Fase 2 — Tools layer enxuta ✅ (2026-05-06)

**O que:** dividir `handlers.py` (1792) e `runtime_dispatch.py` (2253) na nova estrutura `tools/`.

- [x] `blender_addon/tools/` package criado
- [x] `tools/schemas.py` ← TOOLS + AGENT_TOOLS (~370 linhas)
- [x] `tools/client.py` ← `dispatch_tool_raw` + TCP socket (~115 linhas)
- [x] `tools/handlers.py` ← `handlers.py` movido (1 import fix: `from .. import capture`)
- [x] `tools/server_dispatch.py` ← `runtime_dispatch.py` movido + `skill_router.py` inlined
- [x] `tools/reads.py`, `tools/draft.py`, `tools/structural.py` ← stubs de re-export (split completo fica para Fase 4)
- [x] `tools/__init__.py` re-exporta `TOOLS, AGENT_TOOLS, dispatch_tool_raw` (backward compat para `agent_runtime.py`)
- [x] `server.py` atualizado: `from .tools.handlers import HANDLERS`
- [x] `runtime/core.py` atualizado: `from ..tools.server_dispatch import RuntimeDispatcher`
- [x] `tests/test_foundation_stabilization.py`: imports atualizados + bpy-patch path corrigido

**Commits:**
- `b3570ae refactor(slim): tools/ package layer (Fase 2)`
- `dfd717b refactor(slim): remove original handlers.py, runtime_dispatch.py, tools.py, skill_router.py`

**Critério de saída:**
- [x] `blender_addon/handlers.py` deletado
- [x] `blender_addon/runtime_dispatch.py` deletado
- [x] `blender_addon/tools.py` original deletado (substituído pelo package)
- [ ] Smoke test no Blender: `get_scene_summary` retorna dado correto (pendente até Fase 6)
- [x] `write_script_draft` validado em testes unitários (216 tests, 2 falhas pré-existentes)

---

### Fase 3 — Core runtime enxuto ✅ parcial (2026-05-06)

**O que:** substituir `agent_runtime.py` (1857) + `runtime_agent_loop.py` por `core/`.

- [x] Criar `blender_addon/core/` package
- [x] `core/api_client.py` ← move `runtime_api_client.py` pra cá, sem mudança de comportamento
- [x] `core/agent_loop.py` ← loop multi-round Claude API; halt-after-write; truncation guard. Sem comportamento especial de `write_script_draft` no nome — usa hook genérico do handler.
- [x] `core/tool_policy.py` ← contrato de draft (fresh structural memory + draft context + target resolved + evidence) + economy_retry (broad reads bloqueados, focal_budget≥3 em REPAIRING)
- [x] `core/runtime.py` ← `AgentRuntime` enxuto:
  - `run_turn(message)`: load → resolve pending decision → simple intent → handler.handle → save
  - sem dispatcher por turn_class; sem `_workspace_goal_mode` regex; sem `_sync_v1_to_legacy`
  - intent inference resolvida com 4 regras simples (`pending_user_decision.match()` > prefixo `[RESULTADO DE EXECUÇÃO]` > imperativo de escrita explícito > default inquiry)

**Critério de saída:**
- [x] `blender_addon/agent_runtime.py` deletado
- [x] `blender_addon/runtime_agent_loop.py` deletado
- [x] Smoke test: pergunta factual retorna resposta com tree render injetado (validado em sessão real `run-20260506T200924Z-5298c87e`/chat)
- [x] Smoke test: pedido de draft escreve no Text Editor e turno encerra após 1 escrita (validado em sessão real `run-20260506T201023Z-524f1e68`, revisão 38)
- [x] Correção pós-smoke: prefixo `[RESULTADO DE EXECUÇÃO — ...]` e verbo `escrever` agora roteiam para `feedback_fix`/`draft_workspace`
- [x] Verificação local: `python -m compileall blender_addon`
- [x] Verificação local: `python -m unittest discover tests` → 218 tests, 2 falhas pré-existentes

---

### Fase 4 — Handler único + Wave 5.C absorvida ✅ (2026-05-06/07)

**O que:** substituir `runtime/handlers/drafting.py` (2595) + `workspace.py` + `__init__.py` por handler único.

- [x] Criar `blender_addon/handler/` package
- [x] `handler/prompt.py` ← system prompt builder único, com modos: `inquiry`, `diagnose`, `draft`, `feedback`. Sem contrato Sintoma/Hipótese/... obrigatório.
- [x] `handler/workspace.py` ← `handle(goal_mode, ctx)` único:
  - escolhe ferramentas permitidas pelo goal_mode
  - monta system prompt via `prompt.py`
  - chama `core.agent_loop`
  - finaliza turno
- [x] `handler/feedback.py` ← fluxo pós-falha separado: registra feedback, diagnostica revisão falha, emite `PendingUserDecision`, não escreve novo draft
- [x] `runtime/handlers/` removido do caminho vivo; imports migrados para `handler`
- [x] Testes de dispatcher legado reescritos para a superfície `handler.workspace.handle`
- [x] Primeiro corte de `_drafting_support.py`: superfície pública de feedback saiu para `handler/feedback.py`
- [x] Segundo corte de `_drafting_support.py`: leitura da revisão falha, evidência estática, quality gate e fallback saíram para `handler/feedback_evidence.py`
- [x] Terceiro corte de `_drafting_support.py`: política de ferramentas, cobertura semântica e fallback de `goal_guidance` saíram para `handler/draft_policy.py`
- [x] Quarto corte de `_drafting_support.py`: sanitização de chat, resumo de draft e guards de resposta saíram para `handler/draft_response.py`
- [x] Quinto corte de `_drafting_support.py`: leitura/sync de draft e detectores de modo saíram para `handler/draft_state.py`
- [x] Sexto corte de `_drafting_support.py`: inspeção de writes, motivos de não-escrita e retry guidance saíram para `handler/draft_finalize.py`
- [x] Reduzir o restante de `_drafting_support.py` para helpers menores de prompt/contexto do draft workspace (`draft_context.py`, `draft_prompt.py`, `draft_runtime.py`, `feedback_classifier.py`)
- [x] **Wave 5.C absorvida:**
  - `set_pending_decision()` é o único caminho de emitir pergunta A/B
  - resolução de pending decision feita em `core.runtime.run_turn` antes do handler ser chamado
  - guarda contra colapso `STRATEGY_PROPOSED → REPAIRING` no `session_state_store`
  - sem regex nova em `routing_obs.py`
- [x] Pacote de evidência estática (já implementado) consumido pelo prompt em modo `feedback`; instrução é "cite mismatch real se houver", não cabeçalhos exatos.

**Commits adicionais (2026-05-07):**
- `1f61c27 feat: injetar arvore GN completa no system prompt de inquiry` — `_full_tree_render_for_inquiry()` injeta o tree render completo (todos os nós, frames, até 200 links) em todo turno de inquiry; `_inquiry_max_rounds_for_state()` sobe rounds para 7 em REPAIRING/STRATEGY_PROPOSED
- `d61f4e1 fix: bump inquiry rounds in REPAIRING and simplify pending_decision options` — `_inquiry_max_rounds_for_state`; `pending_decision` repair_direction simplificado para `["sim"]`; A/B split só quando ≥2 estratégias
- `ed4baef fix: REPAIRING state write approval and inquiry round bump` — `infer_session_state` em vez de campo raw; roteador detecta REPAIRING e manda confirmação para DRAFT_WORKSPACE mesmo sem draft ativo

**Critério de saída:**
- [x] `blender_addon/runtime/handlers/` deletado inteiro
- [x] Tests state-driven de `tests/test_pending_user_decision.py` passam
- [x] Feedback de falha fica read-only e bloqueia `write_script_draft` até confirmação explícita
- [x] `tree_prompt_render_injected` dispara em todo turno de inquiry com 99 nós, 5073 chars (validado em sessão 2026-05-07)
- [x] "pode" e "sim" em REPAIRING → DRAFT_WORKSPACE (6 novos testes: `RouterRepairingStateTests`, `InquiryMaxRoundsTests`)
- [x] Verificação local: `python -m compileall blender_addon`
- [x] Verificação local: 213 tests verdes

---

### Fase 5 — UI enxuta ✅ (2026-05-07)

**O que:** dividir `ui/panel.py` (1752).

- [x] `ui/operators.py` ← classes `bpy.types.Operator` do painel extraídas (`CHAT_OT_*` e `BLEND_OT_*`)
- [x] Operadores divididos por família: `ui/chat_operators.py` e `ui/cycle_operators.py`, com `ui/operators.py` só agregando registro
- [x] `ui/panel.py` enxuto ← só `draw()` + property registration + render dos 4 estados de `work_cycle_phase`
- [x] Lógica de transição de fase movida para helper dedicado `ui/cycle_state.py`
- [x] Suporte auxiliar separado em `ui/panel_runtime.py`, `ui/panel_workspace.py` e `ui/panel_chat_turn.py`
- [x] Sanitização de código mantida em `ui/chat_session.py` (já está)

**Commit:** `55bde57 refactor(slim): Fase 5 - UI enxuta, panel.py dividido por familia`

**Critério de saída:**
- [x] `ui/panel.py` < 700 linhas (caiu de 1752 → 554 linhas)
- [ ] Os 4 estados visuais ainda funcionam (CONVERSA, PRONTO, EXECUTANDO, RESULTADO) — pendente smoke Fase 6
- [ ] Snapshot + revert ainda funcionam — pendente smoke Fase 6
- [ ] Reabrir `.blend` rehidrata o painel — pendente smoke Fase 6

---

## Handoff — 2026-05-07

### Estado atual

Fases 1–5 completas. Branch `slim-refactor` limpa, 213 testes verdes.

**Módulos ativos:**
- `core/runtime.py`, `core/agent_loop.py`, `core/tool_policy.py`, `core/api_client.py`
- `handler/workspace.py`, `handler/feedback.py`, `handler/feedback_evidence.py`, `handler/draft_prompt.py`, `handler/draft_context.py`, `handler/draft_runtime.py`, `handler/draft_policy.py`, `handler/draft_response.py`, `handler/draft_state.py`, `handler/draft_finalize.py`, `handler/feedback_classifier.py`, `handler/prompt.py`
- `runtime/router.py`, `runtime/routing_obs.py`, `runtime/pending_decision.py`, `runtime/tree_renderer.py`, `runtime/prompt_builder.py`, `runtime/gn_targeting.py`, `runtime/state_ops.py`, `runtime/staged_payload.py`
- `ui/panel.py` (554 linhas), `ui/chat_operators.py`, `ui/cycle_operators.py`, `ui/cycle_state.py`, `ui/operators.py`, `ui/panel_chat_turn.py`, `ui/panel_runtime.py`, `ui/panel_workspace.py`

**Smoke parcial (2026-05-07, sessão testeAgenteBlender.blend, Biomodelo 99 nós):**
- ✅ `tree_prompt_render_injected` dispara em todo inquiry (99 nós, 5073 chars)
- ✅ `script_draft_execution_diagnosis` pós-falha rev 47 correto
- ✅ `pending_decision_proposed` / `pending_decision_cancelled` corretos
- ✅ `discovery_phase_skipped` reutiliza memória estrutural em cache
- ✅ Rev 48 escrita e executada com sucesso ("PERFEITO. Funcionou")
- ⚠️ Inquiry em REPAIRING ainda usava 4 rounds (corrigido pós-sessão via `infer_session_state`)
- ⚠️ "pode" após análise em REPAIRING não acionava write (corrigido pós-sessão no router)

**Bugs corrigidos nesta sessão:**
1. `_inquiry_max_rounds_for_state` lia `execution_state.session_state` diretamente — campo pode não estar hidratado no momento do handler. Corrigido: usa `infer_session_state(ctx.session)` (mesma fonte que o router). Emite `inquiry_rounds_bumped` para observabilidade.
2. Aprovação bare ("pode"/"sim") em REPAIRING sem draft ativo → `context_inquiry` (read-only). Corrigido: router verifica `session_state` antes do gate contextual e roteia para `DRAFT_WORKSPACE` via signal `repairing_write_approval`.

### Próximo passo: Fase 6 — Smoke completo no Blender

Recarregar o addon no Blender (F8 ou Preferences → Addons → Reload) após puxar o branch, depois executar em ordem:

**Bloco 1 — Linha de base (Fases 1-3)**
1. `qual o estado atual da cena?` → `get_scene_summary` + `get_gn_hosts`
2. `mostra o contexto do nó <nome>` → `get_node_context`
3. Fechar/reabrir `.blend` → histórico aparece

**Bloco 2 — Full tree context em inquiry (Fase 4)**
4. Pergunta factual sobre nó específico → journal: `tree_prompt_render_injected`, `node_count=99`
5. "pode" / "sim" após diagnóstico em REPAIRING → deve rotear para DRAFT_WORKSPACE (signal: `repairing_write_approval`)
6. Inquiry em REPAIRING → journal: `inquiry_rounds_bumped`, `effective_rounds=7`

**Bloco 3 — Ciclo pós-falha completo (Wave 5.C)**
7. Draft → executa → reporta falha → agente não escreve no mesmo turno
8. Agente diagnostica e propõe direção → `pending_decision_proposed`
9. "pode" → escreve nova revisão → executa → funciona

**Bloco 4 — UI (Fase 5)**
10. Os 4 estados do painel transitam corretamente (CONVERSA / PRONTO / EXECUTANDO / RESULTADO)
11. Snapshot + revert funcional
12. Reabrir `.blend` rehidrata painel e histórico

### Prompt sugerido para próxima sessão

```text
Estamos no projeto blend_IA_ort_v2, branch slim-refactor. Leia o handoff em docs/SLIM_REFACTOR_PLAN.md (seção "Handoff — 2026-05-07") e o git log. O objetivo desta sessão é completar a Fase 6 (smoke manual no Blender) e, se passar tudo, preparar o merge para master (Fase 7). Reporte os resultados do smoke e liste o que ainda quebrou.
```

---

### Fase 6 — Validação completa no Blender

**O que:** rodar todos os testes manuais do CLAUDE.md §"Como validar que o sistema está funcionando" + acceptance tests do `repair_conversation_loop.md` §9.

**Smoke parcial realizado (2026-05-07, Biomodelo 99 nós):**
- [x] Tree render injetado em todo turno de inquiry (5073 chars, todos os nós)
- [x] `script_draft_execution_diagnosis` pós-falha correto (rev 47)
- [x] `pending_decision_proposed` e transições de estado corretos
- [x] Draft escrito com sucesso (rev 48) e confirmado pelo designer

**Pendente:**
- [ ] Linha de base (1, 2, 3): cena, contexto, persistência (testar em sessão nova)
- [ ] Reabrir `.blend` rehidrata painel e histórico
- [ ] Bridge failure simulada: `structural_memory_recovery_failed` no journal
- [ ] Inquiry em REPAIRING com rounds bumped para 7 (corrigido pós-smoke — verificar no journal: `inquiry_rounds_bumped`)
- [ ] "pode" / "sim" em REPAIRING → `repairing_write_approval` no journal (corrigido pós-smoke)
- [ ] UI Fase 5: 4 estados do painel funcionando
- [ ] Snapshot + revert funcionando
- [ ] Sessão real de 30 min de uso pelo designer

**Critério de saída:**
- [ ] Lista de regressões em `runtime/journal/` curta o suficiente pra fechar
- [ ] PR `slim-refactor` → `master` com diff total negativo de ~7k linhas

---

### Fase 7 — Cleanup e merge

- [ ] Atualizar `CLAUDE.md` para refletir nova estrutura
- [ ] Atualizar `docs/refactor_handoff/REFACTOR_PLAN.md` (marcar Ondas 5–7 como absorvidas pelo slim refactor)
- [ ] Criar `CHANGELOG.md` com sumário do que mudou
- [ ] Merge da branch em `master`
- [ ] Tag `slim-v1`

---

## 7. O que esta refatoração NÃO faz

- Não mexe em `bpy.ops.wm.open_mainfile` / "Enviar e Reverter" — bug separado já endurecido em código
- Não migra para Working Memory layer (Onda 6 do plano antigo) — fica para depois
- Não introduz state machine formal (Onda 7 do plano antigo) — `pending_user_decision` + transições imperativas continuam como estão
- Não toca em `knowledge/domain/*.md` — corpus de domínio é ortogonal
- Não cria o painel paramétrico (Produto B) — ainda é trabalho do designer
- Não mexe em snapshot manager nem em chat_store — funcionam

---

## 8. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Apagar algo que tinha caller invisível | Antes de cada deleção, `Grep` por nome do símbolo em todo o projeto excluindo `legacy/` e `__pycache__/`. Se houver match, parar. |
| Perder invariante por engano | §5 deste doc é checklist obrigatório de smoke após cada fase. |
| Bug novo introduzido em fase intermediária | Cada fase tem smoke manual antes da próxima. Não pular. |
| Refactor estourar prazo | Fases 1, 2, 3 são paralelizáveis em 80% — Fase 1 (deletar) é segura e libera contexto antes das reescritas. Estimativa total: 3–5 dias focados. |
| Trabalho do designer perdido | `master` continua com baseline. Branch é descartável se algo der errado. `.blend` files ficam fora do git mas existem no disco. |
| Wave 5.C ficar pra depois e perder momentum | Ela é absorvida na Fase 4 — não vai ficar pendente. |

---

## 9. Métricas de sucesso

Ao final da Fase 7:

- [ ] **Linhas de código:** addon < 4k linhas Python (atual: ~14k incluindo legacy)
- [ ] **Arquivos > 500 linhas:** zero
- [ ] **Arquivos > 300 linhas:** ≤ 3
- [ ] **Estados de trabalho duplicados:** 1 só (`session_state` em `ExecutionState`, `work_cycle_phase` é apenas hint pro painel)
- [ ] **Regex no router:** zero — substituído por intent inference simples + `pending_user_decision`
- [ ] **Dispatcher de turn_class:** removido — handler único
- [ ] **Tests passando:** todos os de `tests/` que faziam sentido
- [ ] **Smoke Blender:** todos os casos do CLAUDE.md §validação

---

## 10. Decisões já tomadas (não revisitar)

- ✅ **Reaproveitar, não recomeçar.** Os 17 módulos de §1 ficam.
- ✅ **Apagar antes de reescrever.** Fase 1 vem antes da Fase 2.
- ✅ **Wave 5.C entra na Fase 4**, integrada ao novo handler — não como microfrente isolada.
- ✅ **Sem state machine formal nesta refatoração.** Adiada explicitamente.
- ✅ **Sem Working Memory layer nesta refatoração.** Adiada explicitamente.
- ✅ **Branch descartável.** Se a Fase 1 ou 2 mostrar que o plano está errado, voltamos a `master` sem custo.
- ✅ **Nada de `--no-verify`, `--force`, `git config --global`.** Refactor é cirúrgico, não destrutivo.

---

## 11. Próximo passo imediato

**Fase 1 — apagar o legado puro** começa quando o usuário aprovar este plano.

Sequência da Fase 1, comando por comando, sem ambiguidade:
1. `Grep` por callers de cada símbolo da lista de §3
2. Para cada símbolo sem caller real: deletar arquivo / remover do schema / remover handler
3. Rodar `tests/` que sobrevivem; descartar tests dos módulos deletados
4. Smoke manual: addon carrega no Blender, painel abre
5. Commit: `chore(slim): delete dead modules and legacy paths`

Estimativa Fase 1: meio dia.
