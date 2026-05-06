# Refactor Plan — Handlers/Routing + Session/Journal + Context

> Documento único de execução. Substitui todos os docs anteriores desta pasta.
> Atualizado em 2026-05-04 — Onda 4 completa e validada; Onda 5 parcialmente implementada; frente "Repair Conversation Loop" (renomeada a partir de "Post-Failure Diagnosis") documentada em `docs/repair_conversation_loop.md`. Microfrente **Wave 5.C — Conversational State Minimal Layer** introduzida para resolver gargalo de roteamento por regex e colapso de `STRATEGY_PROPOSED` antes da Onda 7.
> **Fonte de verdade deste documento:** ordem de execução, checklist por onda, critérios de saída e dependências. Rationale arquitetural detalhado, `PendingUserDecision` e acceptance tests state-driven vivem em `docs/repair_conversation_loop.md`.
> **Regra de atualização:** quando uma implementação muda, status operacional muda em `CLAUDE.md`; checklist e critérios de saída mudam aqui; mudanças conceituais/acceptance tests mudam em `docs/repair_conversation_loop.md`.
> Como usar: cada onda tem checklist marcável e critério de saída. Avance uma onda por vez. Não pule etapas.

---

## Fora de escopo do agente

O painel de sliders para o profissional de saúde (ortesista, terapeuta) é um **produto separado** do agente.

- Sem chat, sem IA visível, sem código exposto ao usuário.
- O profissional entra medidas clínicas e ajusta parâmetros via sliders — o sistema GN parametrizado responde.
- Este produto começa depois que a **Onda 6** (Working Memory) estiver validada no Blender e a árvore GN tiver atingido parametrização suficiente para um caso clínico real. A Onda 5 (UX do ciclo de trabalho) é pré-requisito prático: o designer precisa de ciclo de execução estável antes de parametrizar a árvore em profundidade suficiente.
- Nenhuma decisão de arquitetura do agente deve ser motivada por "o profissional vai ver isso" — o profissional nunca vê o agente.

**O agente atual (Produto A) é ferramenta de construção para o designer. O painel paramétrico (Produto B) é o produto final para o profissional. São sistemas distintos com ciclos de desenvolvimento distintos.**

---

## 0. Clareza de produto (2026-04-30)

**Dois produtos distintos — nunca confundir:**

- **Produto A (este sistema):** ferramenta de construção para o designer industrial. O agente ajuda a montar e parametrizar a árvore GN. Nunca visto pelo profissional de saúde.
- **Produto B (destino final):** painel paramétrico de sliders/campos para o ortesista/terapeuta. Sem chat, sem IA visível, sem código. Produto do GN parametrizado pelo Produto A.

**Consequência para prioridades:** a qualidade do contexto que o agente tem sobre a árvore GN (nomes de nós, sockets, links) é a métrica principal do Produto A. É esse contexto que determina a qualidade dos scripts que constroem o Produto B.

---

## 1. Visão geral

Duas descobertas relevantes da sessão 2026-04-29 alteraram a prioridade do plano:

**Descoberta A — O agente operava cego à árvore que deve modificar.** Tratado na Onda 4.E: system prompt agora recebe render compacto de árvore nos caminhos validados, `BaselineWorkspace` é reconstruído/usado, e falhas de recuperação estrutural são registradas com `reason`.

**Descoberta B — Economy_retry em REPAIRING bloqueia exatamente as leituras que o agente precisa para sair do estado.** `focal_budget` padrão era 0 em economy_retry. Run `0894ae38`: 5.018 tokens, 0 writes, `interrupted`.

**Nova descoberta (2026-04-30) — O ciclo draft→execução→resultado não existe como interface.** Tudo cai no pipeline de draft; o designer não consegue pensar junto com o agente sem disparar turnos caros; quando um script falha visualmente, não há forma estruturada de comunicar o que aconteceu; Ctrl+Z destrói o draft; histórico de revisões se perde. Este é o principal bloqueador de produtividade identificado em teste manual — entra como Onda 5.

**Princípio que continua válido:** Estado de trabalho explícito decide tudo. A state machine e o handler unificado continuam sendo o destino final — agora com tree context como precondição e ciclo de execução como requisito de UX imediato.

---

## 2. Arquitetura-alvo

### 2.1 Camadas de persistência (destino final)

```
runtime/
├── session_state/        ← identidade + estado operacional mínimo (5–30 KB)
├── chat_history/         ← conversa visível, JSONL append-only
├── working_memory/       ← session_memory, local_scope, baseline compactada
├── journal/runs/         ← debug/telemetria por run_id
├── draft_history/        ← conteúdo de cada revisão de draft por sessão
├── snapshots/            ← .blend snapshots por sessão (Onda 5)
├── tasks/                ← arquivos de tarefa completa: drafts + snapshots (Onda 5)
├── reports/              ← validação e testes
└── archive/              ← legacy import + sessões corrompidas (read-only)
```

### 2.2 Pipeline de turno (destino final — Ondas 4–7)

```
mensagem
    │
    ├── Fast Paths FP1–FP4  (inalterados)
    │
    ▼
[System prompt: _BASE_ROLE + tree_snapshot_render + focus_block + state_hint + guidance]
    │
    ▼
SessionState (lido do session_state/)
    │
    ▼
MessageSignal classifier  (SUCCESS | ERROR | WRITE | EXPLORE | ANY)
    │
    ▼
State Machine: (state, signal) → next_state + goal_mode
    │
    ▼
WorkspaceHandler.handle(goal_mode)
    │
    ├── inquiry             → reads focais, sem write, max 4
    ├── diagnose_only       → reads focais + estruturais, sem write, max 6
    ├── focal_correction    → reads focais + draft_write, max 4
    ├── functional_expansion→ reads estruturais + draft_write, max 5
    └── feedback_fix        → reads focais + draft_write, max 3
                              (focal_budget mínimo=3, sempre, em REPAIRING)
```

### 2.3 Princípios não-negociáveis

1. `execute_code` e `make_plan` permanecem bloqueados no fluxo principal — usuário executa manualmente.
2. Nenhuma camada de persistência sobrescreve outra automaticamente.
3. Sem `IntentResolver` com LLM antes de esgotar opções sem LLM.
4. Sem novas regex no router — quando der vontade de adicionar, é sinal de que falta estado.
5. `blend_path == ""` nunca pode satisfazer lookup de arquivo conhecido.
6. Resumo nunca entra em chat_history como `role=user/assistant`.
7. **Novo (2026-04-29):** A variável de controle de budget é "este turno entregou artefato utilizável?", não "quantos tokens este turno usou?". Um turno de 30k tokens com draft correto é mais barato do que 6 turnos de 5k tokens interrompidos.

---

## 3. Ondas 1–3 — CONCLUÍDAS ✅

### Onda 1 ✅ (2026-04-25)

**Objetivo cumprido:** fonte de verdade estabilizada, dados de routing coletados.

- `SessionV1Store.load()` sem import legacy no hot path
- Quarentena em `archive/quarantine/` para arquivos inválidos
- `journal.start_session()` adiado até `blend_path` resolvido
- `ui_state.session_active` espelhado
- 27+ turnos coletados; análise manual revelou 10/27 classificações incorretas

### Onda 2a ✅ (2026-04-27, validada no Blender)

**Objetivo cumprido:** chat_history separado do session JSON.

- `session/chat_store.py` — `ChatHistoryStore`, JSONL append-only
- `store.save()` zera `history.messages` antes de serializar
- Migração one-shot idempotente; Clear apaga JSONL — validado

### Onda 2b ✅ (2026-04-28)

**Objetivo cumprido:** routing_obs corrigido, override de dispatcher não necessário.

- `infer_turn_intent()` cobre execution_feedback informal e soft-write phrases
- `compute_shadow_handler()` detecta misclassificações críticas
- Reprocessamento 27 turnos: divergência 0%→7.4%, eixo crítico `context_inquiry→draft_workspace` = 0%. Decisão: não implementar override.

### Onda 3 ✅ (2026-04-28, validada no Blender)

**Objetivo cumprido:** journal por run_id, run_id propagado via socket.

- `OperationJournal` grava em `runs/<session_id>/<run_id>.jsonl`
- Índices shardados: `index/sessions.json` + `index/<session_id>.json`
- Eventos verbosos → `debug/<session_id>/<run_id>.jsonl`
- Rotação gzip após 14 dias ou 2 MB
- Fix: `run_id`, `session_id`, `goal_id` propagados no payload `runtime_tool_call`
- Artefatos validados: `runtime/session_state/`, `runtime/journal/runs/`, `runtime/journal/index/`, `runtime/journal/debug/`

---

## 4. Onda 4 — Desbloqueio de contexto ✅ CONCLUÍDA

**Pré-condição:** Onda 3 concluída ✅

**Objetivo:** corrigir os dois bloqueadores imediatos de qualidade (economy_retry + cegueira de árvore) e colapsar os dois handlers de turno em um.

**Sequência obrigatória dentro da onda:** 4a → 4b → 4c → 4d. Não colapsar em um PR único — cada item tem critério de saída que precisa validar antes do próximo.

---

### Item 4a — Desbloquear leituras focais em REPAIRING ✅

**Status (2026-04-29): implementado.**
- `economy_retry_focal_budget = 3 if bool(economy_retry) else 0` em `drafting.py`
- `agent_runtime.py` manteve bloqueio para broad reads e só bloqueia focal reads quando o orçamento chega a `0` ou é esgotado
- Testes unitários focados atualizados e passando com Python do Blender 4.5:
  - `test_draft_workspace_tool_policy_allows_minimum_focal_reads_in_economy_retry`
  - `test_draft_workspace_tool_policy_keeps_minimum_focal_reads_for_unconfirmed_persisted_coverage`
  - `test_economy_retry_allows_three_focal_reads_when_coverage_is_weak`
  - `test_economy_retry_blocks_investigation_and_writes_once`

**Hotfix relacionado (2026-04-29):** o teste manual da Onda 4a expôs dois problemas de UX fora do critério técnico da onda: respostas finais ainda podiam despejar script Python no painel, e "escreve um draft" com artigo indefinido não casava no roteador. Corrigido em `ui/chat_session.py` com sanitização de mensagens finais/histórico e em `runtime/router.py` com padrão explícito para `um/uma draft|script|código`. Testes focados adicionados.

**Arquivo:** `blender_addon/runtime/handlers/drafting.py:1476-1486`

---

### Item 4b — Injetar snapshot de árvore no system prompt ✅ validado no Blender

**Status (2026-04-30): implementado e validado no Blender/journal.**
- Criado `blender_addon/runtime/tree_renderer.py` com `render_compact_tree(snapshot_dict, max_chars=3000)`.
- O renderer aceita snapshot bruto (`nodes`, `links`, `interface`) e `tree_structural_memory` (`major_regions`, `marker`, `parameters`).
- `prompt_builder.py` injeta baseline persistida via `_build_focus_block()` quando `baseline_workspace.structural_summary` está fresca.
- `drafting.py` injeta render da structural_memory fresca no `draft_workspace` e chama `BaselineBuilder.rebuild_from_summary()` com resumo persistível.
- Eventos novos: `baseline_workspace_rebuilt`, `baseline_rebuild_skipped_empty`, `baseline_rebuild_failed`, `tree_prompt_render_injected`.
- Pré-4c fix: `prepare_draft_context` agora preserva `marker.node_names` (até 260), `marker.links` (até 80), `tree_hash` e `freshness` no resumo estrutural.
- Testes unitários focados passaram com Python do Blender 4.5.

**Validação observada na sessão `sess-20260429T143019Z-e909c754`:**
- `run-20260430T191720Z-bb9dd970`: pergunta factual injetou `tree_prompt_render_injected` para `Biomodelo`, `node_count=80`, `marker_node_names_count=80`.
- `run-20260430T194733Z-371620ea`: primeiro draft pós-reabertura injetou árvore, reconstruiu baseline e salvou `GN_Agent_Draft` revisão 12.

**Arquivos envolvidos:**
- `blender_addon/capture.py` — `capture_node_trees_snapshot()` (linha 337) — fonte do dado
- `blender_addon/runtime/prompt_builder.py` — `_build_focus_block()` (linha 110) — onde injetar
- `blender_addon/runtime/handlers/drafting.py` — `_build_draft_workspace_system()` (linha ~1285) — ponto de montagem do system prompt

---

### Item 4c — Unified workspace handler ✅ implementado / validado em uso

**Status (2026-04-30):** handlers principais já passam pelo workspace unificado. Durante a validação 4.E, foram corrigidos problemas de UX do caminho real:
- Perguntas factuais durante `drafting` entram como inquiry read-only e não herdam diagnóstico velho do draft.
- Correções de resposta do agente não terminam em mensagem inútil de "não salvei o draft".
- Diagnóstico/read-only preserva análise útil quando não havia pedido explícito de escrita.
- `write_script_draft` bloqueado por regressão semântica retorna payload detalhado ao modelo e permite uma autocorreção no mesmo turno.
- O loop continua encerrando imediatamente após escrita bem-sucedida.

**Status (2026-04-29):** goal modes principais migrados para `workspace.py`.
- Criado `runtime/handlers/workspace.py` com `GoalConfig` e `GOAL_CONFIGS`.
- `dispatch_turn()` agora roteia `CONTEXT_INQUIRY` e `DRAFT_WORKSPACE` para `workspace.handle(ctx, goal_mode)`.
- `_agent_loop.py` marcado como deprecated/compat bridge.
- `diagnose_only` migrado como modo read-only real; `focal_correction` usa `max_rounds=4`; `functional_expansion` usa `max_rounds=5`; `feedback_fix` usa `max_rounds=3` e mantém `focal_budget_min=3`.
- Hotfixes 4c/4d: `write_script_draft` encerra loop após primeira escrita; diagnóstico curto sem snippets; `diagnose_only` gera diagnóstico mínimo em round-limit; `pure_inquiry` é read-only sem pedido explícito de escrita; `get_tree_parameters` permitido em `diagnose_only`.
- `EXECUTION_FEEDBACK` ainda permanece direto em `drafting.py` nesta fatia.
- Decisão de estado: `workspace.py` não cria segunda state machine; recebe `goal_mode` explícito do dispatcher/meta.

**Critério de saída:**
- [ ] Testes manuais do CLAUDE.md (casos 1–4) passam com o novo handler
- [x] `_agent_loop.py` pode ser marcado `@deprecated` (remoção na Onda 7)
- [ ] `drafting.py` contém apenas `handle_state_control` e funções utilitárias reaproveitadas pelo `workspace.py` — parcialmente atendido; handlers antigos permanecem por compatibilidade até limpeza final.
- [x] Turn router/dispatcher passa `goal_mode` para o workspace em vez de turn_class cru

---

### Item 4d — Revisão de truncamentos ✅ implementado / coberto pela validação 4.E

**Status (2026-04-29): implementado em código.**
- `_MAX_TOOL_RESULT_CHARS`: `4000` → `6000`.
- `_MAX_READ_RESULT_CHARS`: `2500` → `4000`.
- `build_tree_structural_memory` removido de `_HEAVY_READ_TOOLS`.
- `get_scene_summary` e `get_gn_hosts` adicionados a `_HEAVY_READ_TOOLS`.
- `_compress_tool_inputs_in_history()` agora preserva argumentos pequenos/semânticos dos draft tools.
- `AgentRuntime._enforce_draft_tool_policy()` bloqueia `read_script_draft` duplicado em `draft_workspace` quando o pipeline já carregou o draft no início do turno.
- Testes unitários focados passaram com Python do Blender 4.5.

**Critério de saída:**
- [x] Em turn com `draft_workspace`, o agente recebeu tree render compacto antes da escrita — validado no Blender/journal.
- [x] `tree_prompt_render_injected` preserva nomes/links suficientes (`marker_node_names_count=80` nos runs validados).
- [x] Bloqueio semântico de draft não gera loop inútil; o turno pode corrigir e salvar no mesmo run.
- [ ] Total de tokens por turno de `functional_expansion` pode subir — isso é esperado e aceitável se o turno entrega draft.

---

### 4.E — Validação Blender/journal e melhorias imediatas ✅ concluída

**Status (2026-04-30): concluída.** A Onda 5 está liberada.

**Item 4.E.1** — Desserialização de `structural_summary`: verificado sem bug. ✅

**Item 4.E.2** — Aquecimento automático da baseline: primeiro draft pós-reabertura entra com `tree_prompt_render_injected` e `baseline_workspace_rebuilt` no mesmo turno. ✅
- Run validado: `run-20260430T194733Z-371620ea`.

**Item 4.E.3** — Indicador de progresso de turno: **não implementado nesta sessão — absorvido pela Onda 5 como Item 5.1.**

**Item 4.E.4** — Log de falha visível: journal mostra `structural_memory_recovery_failed` com `reason` quando bridge falha. ✅
- Run validado: `run-20260430T202014Z-cd0a8fd5`, `simulate_bridge_failure_active` + `structural_memory_recovery_failed.reason` preenchido.

**Item 4.E.5** — Validação completa 4b/4c/4d no Blender: fechada. ✅

**Critério de saída da Onda 4 completa:** fechado em 2026-04-30.

---

## 5. Onda 5 — UX do ciclo de trabalho (nova — liberada)

**Pré-condição:** Onda 4 completa e validada no Blender ✅ (2026-04-30)

**Por que esta onda entra antes da Working Memory:** o principal bloqueador de produtividade identificado em teste manual não é tamanho de sessão — é que não existe ciclo de trabalho. O designer não tem feedback visual sobre a fase em que o agente está; quando um script falha visualmente, não há forma estruturada de comunicar o que aconteceu; Ctrl+Z destrói o draft; drafts anteriores se perdem; conversa estratégica e turno de draft custam o mesmo. Cada sessão de trabalho é afetada. Este ciclo precisa existir antes de escalar a árvore GN para 400–500 nós.

**Objetivo:** introduzir 4 estados visíveis no painel com transições explícitas, snapshot automático antes de execução, histórico de revisões de draft navegável, e contexto estruturado de resultado. O designer deve poder pensar com o agente (CONVERSA), executar com segurança (EXECUTANDO), e reportar o que aconteceu sem escrever prosa (RESULTADO).

---

### Os 4 estados do ciclo

```
CONVERSA ──(agente propõe draft)──► PRONTO
    ▲                                  │
    │                            (Executar | Descartar)
    │                                  │
(✓ funcionou | ✗ descartou)        EXECUTANDO
    │                                  │
    └──────── RESULTADO ◄──(designer clica "Reportar resultado")
```

| Estado | `execution_state.phase` (V1) | O que o painel mostra |
|---|---|---|
| CONVERSA | `"idle"` | Campo de texto livre; sem botões especiais |
| PRONTO | `"pending_user_execution"` | Draft visível com revisão atual; botões "Executar" e "Descartar" |
| EXECUTANDO | `"executing"` | Instrução de execução; botão "Reportar resultado" em destaque |
| RESULTADO | `"awaiting_feedback"` | Botões ✓/✗; campo de texto; botão "Reverter snapshot" |

**Mapeamento para o V1 existente:**
- `"idle"` já existe em `execution_state` — sem alteração
- `"pending_user_execution"` verifica-se se já existe no schema; se não, adicionar
- `"executing"` e `"awaiting_feedback"` são fases novas — adicionar ao enum de `ExecutionState`

**Estratégia provisória vs. Onda 7 (state machine):**
- Esta onda implementa transições de forma **imperativa**: operadores do painel escrevem `phase` diretamente em `session.execution_state.phase` e chamam `save_v1_session()`
- A Onda 7 substituirá essas transições imperativas por uma máquina de estados formal via `MessageSignal` classifier
- Nenhuma lógica de negócio deve ficar dentro dos operadores de UI — extrair para funções em `runtime/core.py` ou `agent_runtime.py` desde o início para facilitar a migração na Onda 7
- Router não é tocado nesta onda — `EXECUTION_FEEDBACK` absorve o relatório de resultado como turn class existente

---

### Item 5.1 — Indicador de progresso de turno (absorvido de 4.E.3) ⬜

**Arquivo:** `blender_addon/agent_runtime.py` + `blender_addon/ui/panel.py`

**O que fazer:**
- Adicionar `_current_tool_status: str = ""` como atributo de instância em `AgentRuntime`
- Em `runtime_agent_loop.py`, antes de cada `call_blender_socket()`, atualizar `runtime._current_tool_status` com o nome da ferramenta em português (`"Lendo árvore GN..."`, `"Escrevendo draft (round 2/4)..."`, `"Analisando contexto..."`)
- Em `ui/panel.py`, na área de "Processando...", ler `runtime._current_tool_status` via `SESSION.runtime` e exibir o texto dinâmico se não for vazio; fallback: "Processando..."
- Ao fim do turno, zerar `_current_tool_status`

**Não requer:** mudanças em router, schema, snapshot.

**Critério de saída:**
- [ ] Durante um turno de `draft_workspace`, o painel exibe textos diferentes em sequência (não apenas "Processando...")
- [ ] Ao fim do turno, o texto some (campo volta ao normal)
- [ ] Testável sem abrir journal — visível diretamente no painel

---

### Item 5.2 — Schema de fase e revisão de draft em `session/schema.py` 🔶 parcialmente implementado

**Arquivo:** `blender_addon/session/schema.py`

**O que adicionar:**

```python
# Enum de fase do ciclo de trabalho
class WorkCyclePhase(str, Enum):
    IDLE = "idle"
    PENDING_USER_EXECUTION = "pending_user_execution"
    EXECUTING = "executing"
    AWAITING_FEEDBACK = "awaiting_feedback"

# Revisão de draft (uma entrada por write_script_draft bem-sucedido)
@dataclass
class DraftRevision:
    revision: int           # número sequencial (1, 2, 3...)
    timestamp: str          # ISO 8601
    char_count: int         # tamanho do script em chars
    snapshot_ref: str       # nome do arquivo snapshot associado (pode ser "")
    label: str              # descrição curta gerada pelo agente (pode ser "")

# Tarefa em andamento
@dataclass
class TaskInfo:
    task_id: str            # UUID gerado na criação
    label: str              # descrição digitada pelo designer
    started_at: str         # ISO 8601
    ended_at: str           # ISO 8601 ou "" se em andamento
```

**Campos novos em `Session` (ou `ExecutionState`):**
- `work_cycle_phase: WorkCyclePhase = WorkCyclePhase.IDLE`
- `draft_revisions: list[DraftRevision] = field(default_factory=list)`
- `current_revision: int = 0` — índice da revisão atualmente visível no painel
- `current_task: TaskInfo | None = None`

**Migração:** ao carregar sessão V1 sem `work_cycle_phase`, preencher com `"idle"`. Idempotente. Não tocar em `history.messages` (já vazio no JSON).

**O que NÃO fazer:** não criar segundo campo `phase` em `UIState` — manter em `ExecutionState`. Não duplicar estado de draft em dois lugares.

**Status (2026-05-01):** `work_cycle_phase` implementado como campo flat no session dict e lido pelo painel em `_get_runtime_ui_state()` e `_load_local_runtime_session()`. `DraftRevision` e `WorkCyclePhase` como enum formal ainda não adicionados ao `schema.py` — o campo funciona como string flat por enquanto. `draft_revision_count` lido de `len(execution_state.draft_revisions)`.

**Critério de saída:**
- [ ] `schema.py` carrega sem erro; `WorkCyclePhase` importável como enum formal
- [x] Painel lê `work_cycle_phase` do session dict e renderiza layout correto
- [ ] Sessão salva após turno contém `"work_cycle_phase": "idle"` no JSON
- [ ] Sessão antiga sem o campo carrega com default `"idle"` sem exceção
- [ ] `DraftRevision` e `TaskInfo` são serializáveis/desserializáveis pelo `store.py` existente

---

### Item 5.3 — Snapshot manager 🔶 parcialmente implementado

**Arquivo novo:** `blender_addon/snapshot_manager.py`
**Arquivo modificado:** `blender_addon/runtime_dispatch.py` (exposição via socket) + `blender_addon/handlers.py`

**O que implementar:**

```python
# snapshot_manager.py
def take_snapshot(blend_path: str, session_id: str, revision: int) -> str:
    """Salva cópia do .blend antes de execução. Retorna caminho do snapshot."""
    # runtime/snapshots/<session_id>/snap_<timestamp>_r<revision>.blend
    # usa bpy.ops.wm.save_as_mainfile(filepath=..., copy=True)
    ...

def list_snapshots(session_id: str) -> list[dict]:
    """Lista snapshots de uma sessão com timestamp e revisão."""
    ...

def restore_snapshot(snapshot_path: str, target_path: str) -> None:
    """Copia snapshot para target_path. Não abre o arquivo — designer reabre manualmente."""
    ...
```

**Exposição via socket** (ferramentas novas no dispatcher):
- `take_blend_snapshot` — chamado pelo operador "Executar" antes de instruir o designer a rodar o script
- `restore_blend_snapshot` — chamado pelo operador "Reverter snapshot"

**Importante:** o snapshot é uma cópia do `.blend` salva pelo addon (dentro do Blender). O snapshot não requer que o arquivo esteja salvo pelo usuário — usa `copy=True` que não modifica o arquivo original nem os `bpy.data` em memória.

**Journal:** logar `blend_snapshot_taken` com `{session_id, revision, snapshot_path, char_count}` e `blend_snapshot_restored` com `{snapshot_path}`.

**O que NÃO fazer:** não chamar `take_blend_snapshot` automaticamente no loop do agente — só quando o usuário clica "Executar". Não sobrescrever snapshot existente de mesma revisão sem checar.

**Status (2026-05-01):** `snapshot_manager.py` implementado com `take_snapshot()`, `list_snapshots()`, `restore_snapshot()`. `BLEND_OT_execute_draft` chama `take_snapshot()` diretamente (sem socket, evitando deadlock — ver decisão abaixo). `BLEND_OT_revert_snapshot` chama `list_snapshots()` + `restore_snapshot()` diretamente. As ferramentas socket (`take_blend_snapshot`, `restore_blend_snapshot`) estão registradas em `_TOOL_HANDLERS` mas seus métodos correspondentes não foram implementados em `runtime_dispatch.py` — a abordagem direta dos operadores dispensou essa camada.

**Decisão arquitetural (2026-05-01):** operadores de UI chamam `snapshot_manager` diretamente (sem socket), porque chamar `call_blender_socket()` de dentro de um operador Blender (thread principal) causava deadlock: o handler socket tentava `execute_in_main_thread`, que bloqueava o mesmo thread. A camada socket de snapshot permanece não-implementada por não ser necessária.

**Critério de saída:**
- [x] Clicar "Executar" cria `runtime/snapshots/<session_id>/snap_*_r<n>.blend`
- [ ] Journal do turno contém `blend_snapshot_taken` com caminho válido
- [x] Clicar "Reverter snapshot" copia o arquivo e o Blender é reaberto
- [x] `list_snapshots()` retorna lista correta após 3 execuções

---

### Item 5.4 — Painel com 4 estados visíveis 🔶 parcialmente implementado / validado em uso

**Arquivo:** `blender_addon/ui/panel.py` + `blender_addon/ui/chat_session.py`

**O que implementar:**

O `draw()` principal do painel lê `session.work_cycle_phase` e renderiza layout diferente:

**CONVERSA (`idle`):**
- Campo de texto + botão Enviar (comportamento atual)
- Botão "Iniciar tarefa" (chama Item 5.7)
- Indicador de progresso (Item 5.1) quando processing

**PRONTO (`pending_user_execution`):**
- Linha de status: `"Draft pronto — Revisão v{n}"`
- Navegação de revisões: `← v{n-1}` · `v{n}` · `→ v{n+1}` (desabilitado se só uma revisão)
- Botão primário: `"▶ Executar"` — chama operador `BLEND_OT_execute_draft`
- Botão secundário: `"✕ Descartar"` — chama operador `BLEND_OT_discard_draft`

**EXECUTANDO (`executing`):**
- Texto de instrução: `"Execute o script no Text Editor e clique abaixo"`
- Botão primário em destaque: `"📋 Reportar resultado"` — chama operador `BLEND_OT_report_result`

**RESULTADO (`awaiting_feedback`):**
- Botão ✓ `"Funcionou"` — chama `BLEND_OT_result_success`
- Botão ✗ `"Não funcionou"` — chama `BLEND_OT_result_failed`
- Se ✗ clicado: campo de texto livre `"O que aconteceu visualmente?"`; botão `"Capturar screenshot"`; botão `"Reverter snapshot"`
- Botão `"Enviar relatório"` — submete resultado ao agente como turno `EXECUTION_FEEDBACK`

**Transições imperativas (provisórias até Onda 7):**
- `write_script_draft` success → `agent_runtime.py` seta `phase = "pending_user_execution"` + incrementa revisão + chama `save_v1_session()`
- `BLEND_OT_execute_draft` → chama `take_blend_snapshot` via socket + `phase = "executing"` + `save_v1_session()`
- `BLEND_OT_discard_draft` → `phase = "idle"` + `save_v1_session()`
- `BLEND_OT_report_result` → `phase = "awaiting_feedback"` + `save_v1_session()`
- `BLEND_OT_result_success` → `phase = "idle"` + checkpoint snapshot + `save_v1_session()`
- `BLEND_OT_result_failed` → aguarda texto do designer; ao clicar "Enviar relatório" → submete como `EXECUTION_FEEDBACK` + `phase = "idle"` (agente entra em REPAIRING automaticamente via turn_class)

**O que NÃO fazer:** não adicionar regex no router para detectar ✓/✗ — essas são ações de botão, não texto livre. Não criar operadores dentro de `draw()` inline — definir como classes `bpy.types.Operator` separadas.

**Status (2026-05-01):** os 4 estados estão implementados e os operadores funcionam. Bugs corrigidos nesta sessão:
- `_get_runtime_ui_state()` não encaminhava `work_cycle_phase` ao painel — corrigido.
- `_load_local_runtime_session()` lia campo inexistente `current_revision` em vez de `draft_revision` — corrigido.
- `BLEND_OT_execute_draft` e `BLEND_OT_revert_snapshot` usavam socket (deadlock) — refatorados para chamar `snapshot_manager` diretamente.
- `BLEND_OT_result_success` chamava o agente desnecessariamente → atingia round limit — corrigido: sucesso agora apenas seta `idle` e adiciona mensagem local no SESSION sem chamada ao Claude.
- Router: padrão `[RESULTADO]` removido (sucesso não vai mais ao agente); padrão `[RESULTADO DE EXECUÇÃO]` mantido para falhas.
- `_workspace_goal_mode`: `pure_inquiry` em estado REPAIRING não mais força `focal_correction` — evita que perguntas factuais disparem reescrita imediata pós-falha.

**Critério de saída:**
- [x] Com `phase="idle"`: campo de texto aparece; sem botões "Executar"/"Reportar"
- [x] Com `phase="pending_user_execution"`: botões "Executar" e "Descartar" aparecem; campo de texto some
- [x] Com `phase="executing"`: apenas botão "Reportar resultado" em destaque
- [x] Com `phase="awaiting_feedback"`: botões ✓/✗ aparecem; campo de texto aparece após ✗
- [ ] Transições persistem após reabrir Blender (lidas do session JSON) — não validado
- [x] Não há crash quando `current_task` é `None`

---

### Item 5.5 — Draft revision history + navegação ⬜

**Arquivo:** `blender_addon/agent_runtime.py` (escrita) + `blender_addon/ui/panel.py` (navegação)
**Diretório novo:** `runtime/draft_history/<session_id>/r<n>.py`

**O que implementar:**

Quando `write_script_draft` bem-sucedido (journal contém `script_draft_write_succeeded`):
1. Incrementar `session.current_revision`
2. Salvar conteúdo do draft em `runtime/draft_history/<session_id>/r{n}.py`
3. Append `DraftRevision(revision=n, timestamp=..., char_count=..., snapshot_ref=snap_ref_do_turno_anterior)` a `session.draft_revisions`
4. `save_v1_session()`

Navegação no painel (estado PRONTO):
- `← v{n-1}`: decrementa `current_revision`, lê `runtime/draft_history/<session_id>/r{n-1}.py`, envia para Text Editor via socket
- `→ v{n+1}`: incrementa `current_revision`, lê arquivo correspondente, envia para Text Editor

**Ferramenta socket nova:** `load_draft_revision(session_id, revision)` — lê arquivo e abre no Text Editor (via `bpy.data.texts` ou operador). Alternativa: reusar `write_script_draft` com conteúdo lido do arquivo.

**Critério de saída:**
- [ ] Após 3 `write_script_draft` bem-sucedidos: existem `r1.py`, `r2.py`, `r3.py` em `runtime/draft_history/<session_id>/`
- [ ] Setas de navegação aparecem no painel com label `"v3 de 3"` (ou similar)
- [ ] Clicar `←` carrega `r2.py` no Text Editor do Blender
- [ ] Seta `←` desabilitada quando `current_revision == 1`; seta `→` desabilitada quando na revisão mais recente
- [ ] Revisões persistem entre sessões (arquivos em `runtime/draft_history/`)

---

### Item 5.6 — Contexto estruturado de resultado 🔶 parcialmente implementado / problema crítico pendente

**Arquivo:** `blender_addon/agent_runtime.py` + `blender_addon/ui/panel.py`

**O que fazer:**

Quando designer clica "Enviar relatório" (state RESULTADO, ✗):
1. Coletar: `description` (texto digitado), `screenshot_path` (se capturado), `revision`, `snapshot_ref`
2. Formatar como turno `EXECUTION_FEEDBACK` com prefixo estruturado:

```python
structured_prefix = (
    f"[RESULTADO DE EXECUÇÃO — Revisão v{revision}]\n"
    f"Resultado: FALHOU\n"
    f"Descrição: {description}\n"
    f"Snapshot disponível: {snapshot_ref or 'não'}\n"
)
```

3. Submeter como mensagem de usuário — router classifica como `EXECUTION_FEEDBACK` pelo prefixo estruturado ou pelo estado da sessão
4. `phase → "idle"` (agente entra em REPAIRING via `execution_state` existente)

Quando designer clica ✓ "Funcionou":
1. `phase → "idle"`, mensagem de confirmação local no SESSION (sem chamada ao agente)
2. Não renomear snapshot nesta onda — simplificado para evitar complexidade prematura

**Status (2026-05-01):**
- Fluxo ✗ + "Enviar relatório" implementado: `BLEND_OT_send_result_report` envia prefixo estruturado como `EXECUTION_FEEDBACK`. Agente responde discutindo (sem reescrita imediata) e convida o designer a elaborar antes de corrigir.
- Fluxo ✓ "Funcionou" corrigido: não chama mais o agente; apenas mensagem local.
- `handle_execution_feedback` corrigido: não seta mais `pending_draft_action` automaticamente para outcomes de falha — elimina o loop de reescrita imediata que o designer não quer.

**⚠️ Problema crítico: fluxo "Enviar e Reverter" — não resolvido satisfatoriamente (2026-05-01)**

O designer pediu um fluxo combinado: ao dar feedback de falha, querer ao mesmo tempo (a) enviar a descrição ao agente para discussão e (b) reverter o Blender para o estado pré-script.

O problema fundamental: `restore_snapshot()` chama `bpy.ops.wm.open_mainfile()` que recarrega o arquivo `.blend`, destruindo todos os threads em background — incluindo o thread do agente que está processando o feedback.

**Tentativa implementada (2026-05-01):** `BLEND_OT_send_and_revert` em `ui/panel.py`:
1. Envia feedback ao agente (thread background inicia)
2. Copia o snapshot sobre o arquivo `.blend` no disco imediatamente (estado do disco revertido)
3. Não chama `open_mainfile` ainda — seta `_deferred_reopen_path`
4. `_poll_runtime_redraw()` aguarda `SESSION.running == False` (agente terminou) e só então chama `open_mainfile`

**Por que ainda não funciona:** quando o arquivo é reaberto, o Blender carrega o estado do disco (que é o snapshot = estado pré-script). O chat history persiste em JSONL e seria carregado — mas o reopen pode ocorrer antes que a resposta do agente seja gravada no JSONL (o save do JSONL acontece no final do `run_turn()`, e o polling pode disparar o reopen logo após `SESSION.running = False` mas antes do save completar no filesystem). Além disso, o próprio reopen pode causar race conditions com o save sendo feito pelo thread que acabou de terminar.

**O que seria necessário para resolver:**
- Garantir que o JSONL da sessão é flushed antes de disparar o reopen (um `flush()` ou `sync()` explícito no `chat_store` antes de `SESSION.running = False`)
- Ou: mostrar a resposta do agente na UI, e oferecer um botão separado "Reabrir arquivo revertido" que o designer clica manualmente após ler a resposta — sem automação do reopen

**Critério de saída:**
- [x] Clicar ✗ + digitar descrição + "Enviar relatório" → agente recebe contexto estruturado e discute sem reescrever
- [ ] "Enviar e Reverter" funciona corretamente: agente responde E Blender reverte sem perder a resposta
- [x] Clicar ✓ → mensagem local de sucesso; sem chamada ao agente
- [ ] Journal contém `execution_result_reported` com `outcome=failed/success`
- [ ] Snapshot renomeado para `*_checkpoint.blend` em sucesso

---

### Item 5.7 — Marcação de tarefa ⬜

**Arquivo:** `blender_addon/ui/panel.py` + `blender_addon/session/schema.py` (campo `current_task`)

**O que fazer:**

**Botão "Iniciar tarefa"** (visível em estado CONVERSA quando `current_task is None`):
- Abre diálogo (ou `invoke()` com campo de texto) para digitar label: ex. `"Parametrizar flexão do punho"`
- Cria `TaskInfo(task_id=uuid4(), label=label, started_at=iso_now(), ended_at="")` em `session.current_task`
- `save_v1_session()`
- Painel passa a mostrar label da tarefa no cabeçalho do painel

**Botão "Concluir tarefa"** (visível quando `current_task is not None` e `ended_at == ""`):
- Seta `current_task.ended_at = iso_now()`
- Move `runtime/draft_history/<session_id>/r*.py` para `runtime/tasks/<task_id>/drafts/`
- Move snapshots da sessão associados à tarefa para `runtime/tasks/<task_id>/snapshots/`
- Limpa `session.draft_revisions` e `session.current_revision = 0`
- `save_v1_session()`
- Painel volta a mostrar "Iniciar tarefa"

**Escopo mínimo:** a tarefa é por sessão (não há lista de tarefas multi-sessão nesta onda). Multi-tarefa é Onda 8 (Fundação clínica).

**Critério de saída:**
- [ ] "Iniciar tarefa" cria `current_task` no session JSON com `started_at` e `task_id`
- [ ] Label da tarefa aparece no cabeçalho do painel enquanto ativa
- [ ] "Concluir tarefa" seta `ended_at`; arquivos movidos para `runtime/tasks/<task_id>/`
- [ ] Após concluir, `draft_revisions` é vazio e `current_revision = 0`
- [ ] Não há erro quando `current_task is None` em qualquer operação do painel

---

### Critério de saída da Onda 5 completa

- [ ] **5.1:** Texto dinâmico de progresso visível no painel durante turno de `draft_workspace`
- [x] **5.2 (parcial):** `work_cycle_phase` lido do session dict e renderizado corretamente; enum formal no `schema.py` pendente
- [x] **5.3 (parcial):** `runtime/snapshots/<session_id>/` criado ao clicar "Executar"; revert funciona; journal snapshot pendente
- [x] **5.4 (parcial):** Painel exibe 4 layouts corretos; transições funcionam; persistência entre sessões não validada
- [x] **5.5 (parcial):** Revisões completas agora são arquivadas em `runtime/draft_history/<session_id>/rNNNNNN_<block>.py` em cada `write_script_draft` bem-sucedido; navegação ←→ no painel ainda pendente
- [x] **5.6 (parcial):** Relatório ✗ gera `EXECUTION_FEEDBACK` estruturado; agente discute antes de reescrever; "Enviar e Reverter" implementado mas não funcionando corretamente (ver problema crítico no Item 5.6)
- [ ] **5.7:** Tarefa criada, label visível, tarefa concluída com arquivos movidos
- [ ] **Regressão:** testes manuais do CLAUDE.md (itens 1–6) ainda passam

---

### O que esta onda NÃO faz (deixar para ondas posteriores)

- Não cria state machine formal — transições são imperativas até a Onda 7
- Não adiciona regex no router — `EXECUTION_FEEDBACK` absorve os relatórios de resultado pelo prefixo estruturado
- Não cria lista de tarefas multi-sessão — isso é Onda 8 (ClinicalCase)
- Não implementa streaming real do draft sendo escrito token a token — o Text Editor do Blender não tem API de streaming; o draft aparece completo ao final do turno (comportamento atual mantido)
- Não move `working_memory` para diretório separado — isso é Onda 6

---

## 5.B. Frente Repair Conversation Loop (renomeada — paralela à Onda 5)

**Pré-condição:** pode iniciar imediatamente — não bloqueia nem é bloqueada pelos itens 5.1–5.7.

**Documento de referência:** `docs/repair_conversation_loop.md` (renomeado a partir de `docs/post_failure_diagnosis_flow.md`, que agora é apenas stub de redirecionamento).

**Motivação revisada (2026-05-04):** o objetivo continua sendo evitar reescrita prematura após falha. **O foco mudou** de "diagnose_and_propose como formulário rígido" para "ciclo conversacional de reparo": o agente conversa de modo operacional, usa evidência quando há, alinha direção, e só escreve com autorização clara. O contrato Sintoma/Hipótese/Evidência/... vira fallback interno, não formato obrigatório de saída. Roteamento de aprovação passa a ser feito por **estado conversacional** (`PendingUserDecision`), não por regex (Wave 5.C abaixo).

**Invariante central:** Falha de execução não é permissão automática para reescrever. **Mantida.**

### Status real das Waves 1-3 (reconciliação 2026-05-04) 🔶

Documentado como implementado, comportamento parcialmente quebrado em produção. Detalhamento em `repair_conversation_loop.md` §8.

| Wave | Documentado | Realidade observada |
|---|---|---|
| Wave 1 — Minimal safety | concluída ✅ | **funciona** — feedback de falha não dispara reescrita; `draft_history` é fonte primária |
| Wave 2 — Diagnosis quality | concluída ✅ | **comportamento quebrado** — contrato regex falha sistematicamente, fallback template é o que chega ao usuário em todas as falhas observadas (v24, v25, v26 da `sess-20260429T143019Z-e909c754`) |
| Wave 3 — Formal state | concluída ✅ | **schema criado, mas `STRATEGY_PROPOSED` é colapsado para `REPAIRING` no mesmo run pela FSM de fundo**; aprovação curta ("Caminho B") falha por dependência de regex no router |
| Static evidence pack | concluído ✅ | **detector funciona; surfacing é genérico** — `static_evidence_mismatches` real é embutido como string achatada em "Evidencia"; nunca aparece como hipótese principal |
| Wave 4 — UI | pendente ⬜ | bloqueada até Wave 5.C resolver os pontos acima |

A microfrente **Wave 5.C** (abaixo) endereça as três quebras observadas. Não substitui as Waves 1-3 — endurece o que elas pretendiam entregar.

### Wave 4 — UI/UX (mantida pendente)

**Pré-condição revisada:** Wave 5.C concluída e validada no Blender. Sem `PendingUserDecision` resolvendo aprovação por estado, botões de estratégia na UI seriam decoração sobre comportamento quebrado.

- [ ] Botões de estratégia no painel (renderizados a partir de `pending_user_decision.options`)
- [ ] Histórico visual com marcação de falha/sucesso por revisão
- [ ] Indicador visual de "decisão pendente" no painel

---

## 5.C. Wave — Conversational State Minimal Layer (microfrente, 2026-05-04)

**Por que entra antes da Onda 6/7:** os três bugs documentados em §5.B Status (contrato regex falhando, "Caminho B" não reconhecido, `STRATEGY_PROPOSED` colapsando) **já estão afetando o uso diário**. Esperar a state machine completa da Onda 7 para resolver isso significa carregar comportamento quebrado por mais uma onda inteira. Esta microfrente entrega o mínimo necessário para destravar a UX agora, **sem criar duplicidade arquitetural**: as estruturas introduzidas aqui (`PendingUserDecision`, guarda contra colapso de estado, resolução por estado em vez de regex) **são exatamente o que a Onda 7 vai precisar como input** — entram aqui no formato certo desde o início.

**Pré-condição:** pode iniciar imediatamente. Não bloqueia 5.1–5.7. Não bloqueada por elas.

**Documento de referência:** `docs/repair_conversation_loop.md` §2, §6, §10.

**Princípio:** zero regex nova. Estado como fonte de verdade. O helper `set_pending_decision()` é a única forma válida de emitir uma pergunta de decisão. Handlers não devem escrever manualmente perguntas A/B no texto sem registrar a entidade operacional correspondente.

### Item 5.C.1 — Schema `PendingUserDecision` ⬜

**Arquivo:** `blender_addon/session/schema.py`

- [ ] `@dataclass PendingUserDecision` com campos: `kind`, `options`, `prompt_summary`, `source_revision`, `related_failure`, `proposed_at_turn`, `proposed_at_run_id`, `status`, `answered_with`, `answered_at_turn`. Schema completo em `repair_conversation_loop.md` §2.1.
- [ ] Adicionar campo `pending_user_decision: PendingUserDecision | None = None` em `ExecutionState`.
- [ ] `blender_addon/session/store.py`: serialização/desserialização do dataclass; sessões antigas carregam com `None`.

**Critério de saída:**
- [ ] `schema.py` carrega sem erro
- [ ] Sessão antiga sem campo carrega com `pending_user_decision=None`
- [ ] Setar valor + salvar + recarregar produz objeto idêntico

### Item 5.C.2 — Setar pending decision quando o agente pergunta ⬜

**Arquivo:** `blender_addon/runtime/handlers/drafting.py` (handler `handle_execution_feedback`); eventualmente outros handlers que façam pergunta de decisão.

- [ ] Criar/usar helper único conceitual `set_pending_decision()` (ou `emit_decision_prompt()` se o nome final ficar melhor) para materializar perguntas de decisão.
- [ ] Esse helper é o único caminho permitido para perguntas como: escolher A/B, confirmar escrita, autorizar leitura focal, esclarecer escopo ou escolher direção de reparo.
- [ ] Nenhum handler deve terminar com pergunta de decisão ao usuário sem registrar `PendingUserDecision` no mesmo caminho de retorno.
- [ ] Quando o handler emite resposta com opções rotuladas (A/B, conservadora/robusta, etc.), gravar `pending_user_decision` na `ExecutionState` com `kind`, `options`, `source_revision` corretos.
- [ ] **Não inferir** opções pela mensagem do LLM via regex. O handler que **gera** a pergunta também **registra** a decisão pendente — porque ele sabe o que perguntou.
- [ ] Se uma resposta contém opções A/B mas não chama o helper, tratar como bug.
- [ ] Logar `pending_decision_proposed` no journal com `kind`, `options`, `source_revision`.

**Critério de saída:**
- [ ] Após turno de feedback de falha que oferece A/B, sessão V1 contém `pending_user_decision.status="pending"` com `options=["A","B"]` (ou rótulos equivalentes)
- [ ] Reabrir o `.blend` preserva o pending_user_decision
- [ ] Acceptance test cobre que toda resposta com opções A/B materializa `pending_user_decision`

### Item 5.C.3 — Guarda contra colapso de STRATEGY_PROPOSED ⬜

**Arquivos:** `blender_addon/runtime/state_machine.py`, `blender_addon/agent_runtime.py` (final de `run_turn`).

- [ ] Bloqueio explícito: `STRATEGY_PROPOSED → REPAIRING` **só pode ocorrer** quando há ação do próximo turno do usuário (resolução de pending) ou clear explícito do handler. Transição de fim-de-run automática é proibida.
- [ ] Equivalente operacional: enquanto `pending_user_decision.status == "pending"`, `session_state` permanece em `STRATEGY_PROPOSED`.
- [ ] Logar `state_transition_blocked` no journal quando uma transição automática for impedida.

**Critério de saída:**
- [ ] Em run de execution_feedback, journal NÃO contém mais `state_transition: STRATEGY_PROPOSED → REPAIRING` no mesmo run em que o estado foi proposto
- [ ] No turno seguinte, `routing_observation` enxerga `session_state=STRATEGY_PROPOSED`

### Item 5.C.4 — Resolução de pending por estado, não por regex ⬜

**Arquivos:** `blender_addon/runtime/router.py` ou `blender_addon/agent_runtime.py` (início de `run_turn`); `blender_addon/runtime/routing_obs.py`.

- [ ] **Antes** do roteamento normal, checar `session.execution_state.pending_user_decision`. Se `status == "pending"`:
  - Match curto, case-insensitive, contra `options[]`. Suporte mínimo a sinônimos numéricos (`primeira/segunda/1/2`) e a frases-padrão fechadas (`vou pela X`, `fica com a X`, `manda a X`, `caminho X`, `opção X`, `opcao X`). Match é **bound ao conjunto fechado emitido pelo agente**, não regex aberta sobre português.
  - Se mensagem é pergunta (termina com "?", começa com `por que/como/qual`) e não contém match de opção: manter pending, roteamento normal (responder pergunta).
  - Se mensagem é negação clara (`não`, `nenhuma`, `esquece`, `muda`): cancelar pending.
  - Se mensagem é afirmativa curta (`sim`, `pode`, `ok`) sem opção identificada: manter pending; agente pede esclarecimento.
- [ ] `infer_turn_intent()` consome o resultado dessa resolução. Quando resolvido com aprovação, intent é `strategy_approval` (novo) → handler entra em `focal_correction` (write_allowed=true). Quando mantido pending, intent é `pure_inquiry`.
- [ ] **Não adicionar** novas listas regex em `routing_obs.py` (`_SHORT_CONTINUE_PHRASES`, `_SOFT_WRITE_WORDS`, etc.). Quando der vontade de adicionar, é sinal de que o match contra `options[]` precisa ser ajustado, não que falta regex.

**Critério de saída:**
- [ ] "Caminho B", "vou pela B", "sim, a segunda", "manda a B", "opção B" todos resolvem para `B` quando `options=["A","B"]`
- [ ] Mesmas frases NÃO disparam `pure_inquiry → diagnose_only → round_limit`
- [ ] Run de aprovação contém `pending_decision_resolved` no journal com `answered_with`
- [ ] Mensagem ambígua mantém pending e gera resposta de esclarecimento, nunca escolhe lado por conta própria

### Item 5.C.5 — Suavizar contrato pós-falha ⬜

**Arquivos:** `blender_addon/runtime/prompt_builder.py` (`POST_FAILURE_DIAGNOSIS_CONTRACT`); `blender_addon/runtime/handlers/drafting.py` (`_post_failure_contract_status`, `_fallback_post_failure_diagnosis`).

- [ ] System prompt revisto: instrução operacional de "conversa de reparo", não "use exact Portuguese structure". Cita pelo menos um nó/socket/link concreto da `Failed draft static evidence` quando disponível. Termina com no máximo uma pergunta. Se houver opções, rotule A, B (sem prefixos longos).
- [ ] `_post_failure_contract_status()` deixa de ser gate principal. Resposta livre é aceita, mas o limiar mínimo de qualidade deve ser evidência-específico:
  - Se `static_evidence_mismatches` estiver vazio e houver `static_evidence` disponível, exigir ao menos uma referência concreta a nó/socket/link/frame/label.
  - Se `static_evidence_mismatches` NÃO estiver vazio, a resposta principal deve incorporar pelo menos um mismatch na hipótese ou direção proposta.
  - Não basta citar `operation_counts`.
  - Não basta dizer "pode ser problema de sockets ou links".
  - Se o LLM não usa o mismatch real, o fallback roda.
- [ ] `_fallback_post_failure_diagnosis()` continua existindo, mas usa o mismatch real quando `static_evidence_mismatches` não-vazio. O fallback não pode gerar template genérico.
- [ ] Texto não pode ser idêntico em duas falhas seguidas se a evidência for diferente.

**Critério de saída:**
- [ ] Em sessão real de teste, três falhas distintas produzem três respostas distintas (não verbatim do fallback)
- [ ] Quando `static_evidence_mismatches` contém "draft claims no falanges changed, but touched nodes/frames include falange-related names", a resposta menciona esse conflito como hipótese central ou direção de reparo
- [ ] Resposta não usa cabeçalhos `Sintoma:/Hipotese:/...` por padrão; usa quando o LLM julgar útil

### Item 5.C.6 — Acceptance tests state-driven ⬜

**Arquivos:** `tests/test_pending_user_decision.py` (novo); `tests/test_repair_conversation_loop.py` (novo).

- [ ] Cobrir Tests 1–9 de `repair_conversation_loop.md` §9, incluindo o Teste 5b de fallback com mismatch real.
- [ ] Sem dependência de Blender; usar mock de `Session/ExecutionState`.
- [ ] **Anti-regressão crítico:** "Caminho B", "vou pela B", "sim, a segunda" devem todos resolver SEM nova regex em `routing_obs.py`.

### Critério de saída da Wave 5.C completa

- [ ] **5.C.1:** `PendingUserDecision` no schema, persiste em V1, sobrevive a reload
- [ ] **5.C.2:** Handler de feedback seta pending automaticamente ao perguntar A/B
- [ ] **5.C.3:** STRATEGY_PROPOSED não é mais colapsado para REPAIRING no mesmo run
- [ ] **5.C.4:** Aprovação A/B funciona sem nova regex; ambiguidade vira pergunta de esclarecimento
- [ ] **5.C.5:** Resposta pós-falha não é mais idêntica entre falhas distintas
- [ ] **5.C.6:** Tests 1–9 passam

### O que esta microfrente NÃO faz

- Não substitui o router atual completamente — isso é Onda 7 (Frente B).
- Não cria state machine formal — `pending_user_decision` é parte do `ExecutionState`, não uma máquina paralela.
- Não introduz LLM intent classifier por turno — match é estrutural sobre `options[]` emitidas.
- Não adiciona UI nova — Wave 4 da frente Repair Conversation Loop continua pendente, agora com pré-condição revisada.
- Não toca em `working_memory` — isso é Onda 6.

### Integração com Onda 7

`PendingUserDecision` é **input** para a state machine formal da Onda 7 (Frente B), não substituída por ela. Quando a Onda 7 introduzir `MessageSignal` e `VALID_TRANSITIONS`, o `pending_user_decision` é consultado pelo classifier antes de qualquer match de signal. Estados como `STRATEGY_PROPOSED` e `STRATEGY_APPROVED` da Wave 3 são absorvidos pelo conjunto formal de estados — não duplicados.

A guarda contra colapso de estado (Item 5.C.3) é **antecipação do contrato da Onda 7**: na state machine formal, transições só ocorrem por `MessageSignal`, nunca por timer/limpeza. O bloqueio implementado nesta microfrente apenas força esse contrato cedo.

---

## 6. Onda 6 — Working Memory layer (bloqueada até Onda 5 validada no Blender)

**Pré-condição:** Onda 5 completa e validada no Blender. Não iniciar antes.

**Objetivo:** tirar memória operacional de dentro do Session State; Session V1 fica < 30 KB.

**Frente B — Working Memory**

- [ ] Criar `runtime/working_memory/<session_id>.json`
- [ ] Mover de `Session V1` para working_memory:
  - `operational_state.session_memory`
  - `operational_state.local_scope`
  - `operational_state.structural_index`
  - `operational_state.tree_structural_memory`
  - `baseline_workspace.*` (fica como cache derivado, recalculável via `BaselineBuilder`)
- [ ] Session V1 fica pequeno (5–30 KB): `identity`, `focus`, `execution_state` mínimo, ponteiros
- [ ] `recent_actions` e `risky_events` enxugados drasticamente
- [ ] Migração lazy: ao abrir Session V1 existente sem `working_memory/` correspondente, extrair automaticamente e gravar `working_memory/<session_id>.json`. Logar `migration_v1_to_v6` no journal. Idempotente.
- [ ] Session V1 mantém campos originais como read-only por 1 release para rollback

**Critério de saída da Onda 6:**
- Session V1 médio < 30 KB
- `runtime/working_memory/<session_id>.json` existe e contém `tree_structural_memory` persistido
- `BaselineWorkspace` é reconstruído de `working_memory` no load (não de V1)
- Testes manuais do CLAUDE.md ainda passam

---

## 7. Onda 7 — Limpeza arquitetural (bloqueada até Onda 6 validada no Blender)

**Pré-condição:** Onda 6 completa e validada no Blender. Não iniciar antes.

**Objetivo:** eliminar a dívida técnica acumulada nas Ondas 1–6. Três frentes independentes mas com dependências entre si.

---

### Frente A — `drafting.py`: extrair responsabilidades

`drafting.py` concentra hoje: lógica de goal_mode, policy de ferramentas, gerenciamento de estado de draft, construção de system prompt do workspace, lógica de finalização, render de memória estrutural, e helpers de regex internos. `workspace.py` delega de volta para ele em quase tudo — o encapsulamento é cosmético.

- [ ] Identificar as fronteiras de extração sem quebrar os testes existentes:
  - `_draft_workspace_tool_policy()` → `runtime/tool_policy.py`
  - `_compact_structural_memory()` e `_prepare_structural_memory()` → absorvidos por `tree_renderer.py` (já tem `render_compact_tree`)
  - `_finalize_draft_workspace_attempt()` → `workspace.py` (o finalizador pertence ao handler, não ao pipeline)
  - `handle_state_control()` → manter em `drafting.py` como único handler legítimo restante
- [ ] `drafting.py` ao final desta frente contém apenas: `handle_state_control`, `handle_execution_feedback`, e funções utilitárias sem estado chamadas por `workspace.py`
- [ ] `_agent_loop.py` removido (depreciado na Onda 4c)

---

### Frente B — `router.py`: substituir regex por state machine

O router tem >150 linhas de listas `re.Pattern` em 17 grupos. Vai crescer linearmente com novos domínios (próteses, splints funcionais, orteses pediátricas). A state machine é a única arquitetura que escala sem manutenção de regex.

- [ ] **Decisão obrigatória antes do primeiro commit:** `state_machine.py` atual tem fases `idle/reading/drafting/failed/halted`. Escolher: (a) expandir com estados novos (`IDLE/EXPLORING/PENDING_USER_EXECUTION/REPAIRING/RESOLVED`), depreciando os antigos; ou (b) substituir inteiramente. Não criar dois sistemas de estado em paralelo.
- [ ] **Nota de integração com Onda 5:** as transições imperativas de fase (`idle → pending_user_execution → executing → awaiting_feedback`) implementadas na Onda 5 devem ser migradas para as transições formais da state machine nesta frente. Não duplicar — substituir.
- [ ] `MessageSignal` enum: `SUCCESS | ERROR | WRITE | EXPLORE | ANY`
- [ ] `classify_message_signal(msg, session)` substitui o router atual — sinal simples, não regex exaustiva
- [ ] `VALID_TRANSITIONS: {state: {signal: next_state}}` mapeia todas as transições, incluindo as do ciclo de trabalho da Onda 5
- [ ] Dispatcher: `state + signal → next_state + goal_mode → workspace.handle`
- [ ] Router simplificado para 3 turn_classes: `TRIVIAL_CHAT`, `WORKSPACE`, `STATE_CONTROL`
- [ ] `EXECUTION_FEEDBACK` absorvido pelas transições de estado:
  ```
  PENDING_USER_EXECUTION + SUCCESS → RESOLVED
  PENDING_USER_EXECUTION + ERROR   → REPAIRING
  ```

---

### Frente C — `agent_runtime.py`: fronteira de responsabilidade clara

`agent_runtime.py` com >1000 linhas contém: `DraftAttemptContract`, `DraftAttemptState`, economy_retry, gestão de sessão V1+legacy, knowledge updater, e policy enforcement. A fronteira entre "orquestrador de turno" e "policy engine" não está clara.

- [ ] Extrair `DraftAttemptContract` + `DraftAttemptState` para `runtime/draft_attempt.py`
- [ ] Eliminar dual persistence (legacy + V1): remover `session_store.py` e `_sync_v1_to_legacy()`
- [ ] `agent_runtime.py` ao final desta frente contém apenas: orquestração de turno (carregar sessão → classificar → despachar → salvar) e nada mais
- [ ] `runtime/draft_history/<session_id>/<revision>.py` — já implementado na Onda 5; esta frente garante que os checkpoints são feitos antes de cada `write_script_draft`

---

**Critério de saída da Onda 7:**
- `_agent_loop.py` removido; `drafting.py` contém apenas handlers legítimos e utilitários sem estado
- `router.py` não tem grupos de regex — usa `MessageSignal` classifier
- `agent_runtime.py` < 300 linhas, sem `DraftAttemptContract` e sem dual persistence
- Transições de fase da Onda 5 migradas para state machine formal
- Todos os testes manuais do CLAUDE.md ainda passam

---

## 8. Onda 8 — Fundação do produto final (bloqueada até Onda 7 concluída)

**Pré-condição:** Onda 7 concluída. A árvore GN deve ter parametrização suficiente para ao menos um caso clínico real antes de investir nesta onda.

**Objetivo:** introduzir as entidades de domínio clínico que o Produto B (painel paramétrico) vai exigir. Esta onda não constrói a interface do profissional de saúde — constrói a fundação de dados que a viabiliza.

---

### Frente A — `ClinicalCase` como entidade de primeira classe

Hoje o identificador de caso é o `blend_path`. Renomear o arquivo .blend quebra a sessão. Numa plataforma multi-caso, isso é inaceitável.

- [ ] Schema `ClinicalCase`:
  ```python
  @dataclass
  class ClinicalCase:
      case_id: str          # UUID gerado na criação, nunca muda
      patient_id: str       # opaco — não armazena dados pessoais no código
      device_type: str      # "wrist_orthosis" | "thumb_splint" | etc.
      measurements: dict    # chave: nome clínico, valor: float + unidade
      revision_history: list[CaseRevision]
      blend_path: str       # referência, não identificador
      created_at: str
      updated_at: str
  ```
- [ ] `case_id` como chave primária de lookup em `SessionV1Store` (substitui hash de `blend_path`)
- [ ] Migração lazy: sessões existentes recebem `case_id` gerado a partir do hash atual — idempotente
- [ ] `runtime/cases/<case_id>.json` — arquivo de caso separado do arquivo de sessão
- [ ] **Nota:** `TaskInfo` da Onda 5 (tarefa de designer) é distinta de `CaseRevision` (revisão clínica). `TaskInfo` representa trabalho do designer; `CaseRevision` representa um estado paramétrico entregável ao profissional. A Onda 8 vincula os dois.

---

### Frente B — Schema clínico com validação de range

- [ ] `knowledge/domain/clinical_schema.py` (ou YAML) — define parâmetros clínicos canônicos:
  ```python
  CLINICAL_PARAMETERS = {
      "forearm_length":  {"unit": "mm", "range": (150, 400), "gn_identifier": "forearm_length"},
      "wrist_width":     {"unit": "mm", "range": (40, 120),  "gn_identifier": "wrist_width"},
      "wrist_angle":     {"unit": "deg", "range": (-90, 90), "gn_identifier": "wrist_angle"},
  }
  ```
- [ ] Validação de range ao receber medidas clínicas — aviso ao designer quando valor fora do range esperado
- [ ] `map_clinical_parameter_roles` usa este schema como fonte de verdade
- [ ] O agente cita nomes clínicos canônicos em vez de nomes internos de nó GN

---

### Frente C — Rastreabilidade de revisões clínicas

- [ ] `CaseRevision`: snapshot de `measurements` + `draft_content` + `timestamp` + `designer_note`
- [ ] Gravado automaticamente quando tarefa da Onda 5 é concluída com sucesso (snapshot de checkpoint)
- [ ] `runtime/cases/<case_id>/revisions/<revision_id>.json`
- [ ] Permite ao designer voltar a um estado paramétrico anterior sem depender do undo do Blender

---

**Critério de saída da Onda 8:**
- Renomear o arquivo .blend não quebra a sessão (lookup por `case_id`)
- `map_clinical_parameter_roles` usa `CLINICAL_PARAMETERS` como fonte de verdade
- Revisões de caso são persistidas e o designer consegue listar e restaurar revisões anteriores
- O Produto B (painel paramétrico) tem a fundação de dados necessária para ser construído como sistema separado

---

## 9. Riscos críticos

| Onda | Item | Risco | Mitigação |
|---|---|---|---|
| 4a | REPAIRING focal reads | Focal reads desbloqueados fazem o agente looping em leituras sem escrever | `max_rounds` permanece em 3 para `feedback_fix`; bloquear `build_tree_structural_memory` (broad) mesmo com focal desbloqueado |
| 4b | Tree injection | Snapshot grande demais → system prompt excede context window | Renderer com teto de 3000 chars; para >200 nós, priorizar frames > nomes > links |
| 4b | BaselineBuilder caller | `rebuild_from_summary()` chamado com structural_summary incorreto ou vazio persiste dado inútil | Validar que structural_memory tem `node_count > 0` antes de chamar; logar `baseline_rebuild_skipped_empty` se não |
| 4c | Unified handler | Migrar `focal_correction` quebra path que funcionava | Migrar 1 goal_mode por vez; manter handlers antigos funcionais como fallback por 1 release |
| 4c | state_machine.py | Dois sistemas de estado rodando ao mesmo tempo divergem | Decisão de migração documentada antes do primeiro commit da Onda 4c |
| 4d | Truncamento aumentado | Contexto maior → latência e custo por turno sobem | Aceitar o custo; monitorar via journal `api_usage`; a métrica de sucesso é "turnos com entrega", não tokens |
| 5.3 | Snapshot manager | `bpy.ops.wm.save_as_mainfile` bloqueia thread ou falha silenciosamente em arquivos grandes | Executar em handler Blender-side (dentro do socket dispatch, não em thread background); logar falha com razão |
| 5.4 | Painel 4 estados | Estado `phase` diverge entre UI e sessão V1 (cache stale) | UI sempre lê `phase` do session JSON na abertura do painel; operadores salvam e releem antes de renderizar |
| 5.4 | Transições imperativas | Operador de UI seta `phase` errado (ex: `executing` sem ter feito snapshot) | Sequência de pré-condição no operador: checar snapshot antes de permitir "Executar"; se falhar, permanecer em `pending_user_execution` e logar |
| 5.5 | Draft history | Arquivo de revisão não gravado (falha de disco) → navegação quebrada | Verificar existência de arquivo antes de mostrar seta de navegação; seta desabilitada se arquivo não existe |
| 5.6 | Contexto estruturado | Prefixo estruturado não roteado como `EXECUTION_FEEDBACK` → agente responde como chat normal | Verificar no router que prefixo `[RESULTADO DE EXECUÇÃO` dispara turn_class correto; testar com teste unitário focado |
| 5.C | PendingUserDecision | Handler esquece de setar `pending_user_decision` ao perguntar A/B → resolução por estado fica desativada | Usar helper `set_pending_decision()` único; teste anti-regressão garante que toda resposta com opções A/B materializa a entidade |
| 5.C | PendingUserDecision | Match contra `options[]` é frágil e exige nova regex caso por caso | Match restrito ao conjunto fechado emitido pelo agente; sinônimos numéricos e frases-padrão são lista pequena e fechada; ambiguidade vira pergunta de esclarecimento, não nova regex |
| 5.C | Guarda de STRATEGY_PROPOSED | Bloqueio absoluto da transição automática trava sessão se o handler esquecer de chamar `clear` | `pending_user_decision` tem `expired` por idade (5 turnos sugerido); `clear` explícito sempre disponível para o handler |
| 5.C | Suavização do contrato | LLM produz resposta vaga que passa pelo limiar de qualidade → designer recebe baixa qualidade sem fallback | Limiar evidência-específico: sem mismatch, exigir referência concreta a nó/socket/link/frame/label quando houver evidência; com mismatch, exigir que a hipótese/direção use o mismatch real. `operation_counts` e "sockets ou links" genérico não bastam |
| 6 | Working memory | Migração lazy falha mid-write, working_memory fica parcial | Migração idempotente; verificar existência completa antes de usar; em falha, regredir para V1 e logar |
| 7 | State machine | Transições de fase da Onda 5 (imperativas) e state machine formal da Onda 7 divergem | Substituir completamente — não coexistir; migrar operadores de UI para usar `MessageSignal` em vez de `phase` direta |
| 7 | State machine | `PendingUserDecision` da Wave 5.C duplicaria com classifier da Onda 7 | Onda 7 consome `pending_user_decision` como input do classifier, não substitui; estados `STRATEGY_PROPOSED`/`STRATEGY_APPROVED` são absorvidos pelo enum formal |

---

## 10. Decisões já tomadas (não revisitar sem dado novo)

- ✅ **Não adicionar mais regex no router.** Cada incidente que daria vontade de adicionar regex é evidência a favor da state machine (Onda 7) e/ou de `PendingUserDecision` (Wave 5.C).
- ✅ **Não implementar IntentResolver com LLM.** Custo permanente por turno; state machine + `PendingUserDecision` resolvem sem LLM.
- ✅ **`execute_code` e `make_plan` ficam bloqueados** no fluxo principal.
- ✅ **Import legacy nunca no hot path de leitura.**
- ✅ **Não implementar override de dispatcher** (Onda 2b): divergência `context_inquiry→draft_workspace` = 0/27 (0%), abaixo do limiar de 10%.
- ✅ **Broad reads bloqueados em economy_retry** (correto): o agente não deve refazer exploração completa em REPAIRING. Apenas leituras focais são necessárias.
- ✅ **Focal reads devem ser permitidos em REPAIRING** (2026-04-29): `focal_budget=0` padrão em economy_retry é um bug, não uma feature. Prova: run `0894ae38`.
- ✅ **A variável de controle de orçamento é entrega, não tokens.** Um turno que consome 30k tokens e entrega draft correto é mais eficiente do que 6 turnos de 5k tokens interrompidos.
- ✅ **`BaselineWorkspace` precisa de caller antes de ser útil.** A assinatura SHA-1 e a estrutura de dados estão corretos (`session/baseline.py`). O renderer e o caller foram implementados na Onda 4b.
- ✅ **`build_tree_structural_memory` não pertence a `_HEAVY_READ_TOOLS`.** Corrigido na Onda 4d.
- ✅ **Streaming do draft no painel não é viável nesta onda.** O Text Editor do Blender não tem API de streaming; o draft aparece completo ao final do turno. Não implementar solução de polling artificial.
- ✅ **Transições de fase da Onda 5 são imperativas (provisórias).** A state machine formal da Onda 7 vai substituí-las — não coexistir com elas. Toda lógica de transição vai para funções em `runtime/core.py` desde o início para facilitar a migração.
- ✅ **Pós-falha é conversa de reparo, não formulário diagnóstico** (2026-05-04). O contrato `Sintoma:/Hipotese:/Evidencia:/...` deixa de ser formato obrigatório de saída e passa a ser fallback interno. Detalhes em `docs/repair_conversation_loop.md`.
- ✅ **Aprovação humana de estratégia é resolvida por estado, não por regex** (2026-05-04). `PendingUserDecision` (Wave 5.C) é a única estrutura que escala para reconhecer "Caminho B", "vou pela B", "opção B", "sim, a segunda" sem manter listas lexicais. Adicionar nova entrada em `_SHORT_CONTINUE_PHRASES` é proibido.
- ✅ **`STRATEGY_PROPOSED` não pode colapsar para `REPAIRING` no mesmo run** (2026-05-04). Bug observado em `runtime/journal/runs/sess-20260429T143019Z-e909c754/run-20260504T145800Z-87e94235.jsonl:9-12` (idem para v25, v26). Wave 5.C implementa a guarda; Onda 7 herda o contrato.
- ✅ **Resposta pós-falha não é idêntica entre falhas distintas.** Quando o LLM produz texto livre que cita evidência concreta, o sistema aceita. O fallback só roda quando o LLM falha de fato (vazio/erro/abaixo do limiar evidência-específico), e o fallback incorpora `static_evidence_mismatches` quando presente.

---

## Atualização 2026-05-01 (sessão 10)

**Fluxo "feedback + reverter" — hardening implementado em código, validação Blender pendente**

- `ChatHistoryStore.append()` agora faz `flush()` + `os.fsync()` antes do turno ser observado como encerrado.
- `SessionV1Store.save()` agora grava em arquivo temporário e usa `replace()` atômico, reduzindo risco de JSON parcial no reopen.
- `ui/panel.py::_run_chat_turn()` agora só seta `SESSION.running = False` depois de adicionar a resposta final do assistente ao `SESSION`.
- `ui/panel.py::_poll_runtime_redraw()` agora só libera o reopen quando existe uma nova mensagem final do assistente no `SESSION`.
- Teste novo: `tests/test_session_persistence_durability.py`.

**Status:** a race principal documentada no Item 5.6 foi endurecida em código. Ainda falta validação manual no Blender para confirmar que "Enviar e Reverter" preserva a resposta do agente após o reload real do `.blend`.

**Correção adicional da sessão 10:** `_on_blend_load_post()` chamava `rt.clear_history()` após `open_mainfile()`. Esse método apaga o JSONL persistido, então o próprio reload do snapshot destruía o histórico recém-gravado. Foi criado `AgentRuntime.clear_runtime_context()` para limpar apenas contexto volátil (`_messages` e `_active_v1_session`), e o `load_post` passou a usar esse método. O botão Clear continua usando `clear_history(blend_path=...)`.

**Status revisado:** o fluxo "Enviar e Reverter" agora preserva a camada de sessão/chat em código; falta validação manual no Blender para confirmar a reidratação visual após o reload real.

**Ajuste UX relacionado (sessão 10):** os runs `run-20260501T201710Z-f4a9881c` e `run-20260501T202430Z-5c1e0088` confirmaram `script_draft_write_succeeded` para `GN_Agent_Draft` v17/v18. A dificuldade de teste veio da UX: o botão "Executar" não abria o Text Editor nem validava a existência do bloco. `BLEND_OT_execute_draft` agora abre o draft atual antes de criar snapshot/avançar; se o bloco não existir, cancela. Também foi adicionado `BLEND_OT_open_draft`.

**Ajuste adicional:** adicionado `BLEND_OT_run_draft`, um botão manual no painel que executa o `GN_Agent_Draft` via `bpy.ops.text.run_script()` com contexto de Text Editor. Isso mantém a regra de não autoexecutar pelo agente: a execução acontece somente por clique explícito do designer. Após a tentativa, o painel entra em `awaiting_feedback`.

**Diagnóstico/journal e draft history (sessão 10):**
- Journals recentes (`run-20260501T202430Z-5c1e0088`, `run-20260501T205051Z-fd341caf`, `run-20260501T205253Z-ffd4b1aa`) mostram que os drafts v18/v21 foram escritos, mas o feedback de falha ainda podia virar registro raso sem diagnóstico e uma pergunta do designer sobre o draft podia virar reescrita.
- `_workspace_goal_mode()` agora preserva `pure_inquiry` como `diagnose_only` em REPAIRING/retry pendente, mesmo quando a pergunta contém a palavra "draft".
- `handle_execution_feedback()` agora tenta diagnosticar automaticamente qualquer outcome ruim, relendo o draft atual e usando structural memory antes de pedir mais detalhe.
- `write_script_draft` passa a salvar o conteúdo completo do script em `runtime/draft_history/<session_id>/rNNNNNN_<block>.py` quando o runtime fornece `session_id/project_root`. Isso resolve a parte de persistência de conteúdo do Item 5.5; navegação visual por revisão ainda falta.

---

## Atualização 2026-05-04 — Reframing arquitetural da frente pós-falha

**Decisão arquitetural revisada:** a frente "Post-Failure Diagnosis Flow" foi renomeada para "Repair Conversation Loop" e o foco mudou. O documento `docs/post_failure_diagnosis_flow.md` foi reduzido a stub de redirecionamento; o documento ativo é `docs/repair_conversation_loop.md`. O nome interno do modo (`diagnose_and_propose`) pode permanecer no código, mas conceitualmente ele é um modo de **conversa**, não um formulário diagnóstico.

**O que mudou (resumo):**

1. O contrato `Sintoma:/Hipotese:/Evidencia:/Confianca:/Limitacoes:/Opcoes:/Pergunta:` deixa de ser formato obrigatório de saída e passa a ser fallback interno. Resposta livre do LLM que cite evidência concreta é aceita.
2. Aprovação humana de estratégia ("Caminho B", "vou pela B", "opção B", "sim a segunda") é resolvida por **estado conversacional** (`PendingUserDecision`), não por novas regex.
3. `STRATEGY_PROPOSED` não pode mais colapsar para `REPAIRING` automaticamente dentro do mesmo run.
4. Static evidence detectada (`static_evidence_mismatches`) deve aparecer na hipótese principal da resposta, não enterrada como string achatada em "Evidencia".

**Microfrente nova: Wave 5.C — Conversational State Minimal Layer.** Detalhada na §5.C. Entra antes da Onda 6/7 porque os bugs documentados (contrato regex falhando consistentemente, "Caminho B" não reconhecido, STRATEGY_PROPOSED colapsando) já estão afetando o uso diário. Estruturas introduzidas (`PendingUserDecision`, guarda de transição, resolução por estado) **são input** da state machine formal da Onda 7, não duplicidade.

**Evidência que motivou a revisão:**

- Sessão real `sess-20260429T143019Z-e909c754` (runs 04-mai): três falhas seguidas (v24, v25, v26) recebem resposta-template idêntica do `_fallback_post_failure_diagnosis()`; `static_evidence_mismatches` real ("draft claims no falanges changed, but touched nodes/frames include falange-related names") é gerado e ignorado pela resposta.
- Mesma sessão: "Caminho B" e "sim segue para a estrategia B" caem em `pure_inquiry → diagnose_only → round_limit` em runs `151938Z` e `152101Z`. "Segue pela A" funciona apenas porque "segue" está em `_SHORT_CONTINUE_PHRASES`.
- Mesma sessão: `state_transition: STRATEGY_PROPOSED → REPAIRING` ocorre dentro do mesmo run de `script_draft_execution_diagnosis` em runs `145800Z`, `151831Z`. O estado pós-falha nunca chega ao turno seguinte.

**Próximo passo recomendado:** iniciar Wave 5.C imediatamente. Não bloqueia 5.1–5.7. Não bloqueada por elas. Critério de saída autônomo. Suite de tests state-driven (`tests/test_pending_user_decision.py`) exequível sem Blender.
