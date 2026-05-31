# CLAUDE.md — blend_IA_ort

> **Status atualizado 2026-05-31:** slim refactor ✅ **concluído e mergeado em `master`**. Branch `slim-refactor` encerrada. Referência operacional viva do fluxo atual: `docs/refactor_handoff/LIVE_FLOW.md`. Estado validado: `python -m pytest -q` → **185 passed** (1.2s, sem Blender); smoke Blender `ok: true`. Para entender o fluxo real do sistema use `LIVE_FLOW.md` — este `CLAUDE.md` contém histórico valioso do refactor mas várias seções internas ainda descrevem o estado pré-slim. As divergências conhecidas estão marcadas ao longo do documento.

> ~~**Branch `slim-refactor`**~~ **CONCLUÍDA.** Os módulos listados como "a deletar" neste CLAUDE.md já foram removidos. `docs/SLIM_REFACTOR_PLAN.md` é referência histórica; as fases estão concluídas. Divergências conhecidas neste documento: (1) seção "Fluxo de runtime" referencia módulos deletados — ver versão corrigida abaixo; (2) seção "Truncamentos" aponta para `runtime_agent_loop.py` (deletado) — ver nota na seção; (3) "Falhas conhecidas Wave 5.C" item (c) está corrigido no código; (4) "Persistência de sessão" ainda descreve três stores — o store legacy foi removido; (5) a árvore de diretórios no bloco de código a seguir é histórica, **não use como referência operacional**.
>
> **Fonte de verdade:** `docs/refactor_handoff/LIVE_FLOW.md` para fluxo e arquivos vivos; `docs/repair_conversation_loop.md` para o loop de reparo pós-falha; este arquivo para regras do agente e contexto histórico.

---

## Dois produtos distintos

Esta distinção é crítica e deve guiar todas as decisões de arquitetura e prioridade.

### Produto A — O agente (este sistema)

**Quem usa:** o designer industrial que constrói o sistema de Geometry Nodes.

**O que é:** ferramenta de construção. O designer conversa com o agente no painel lateral do Blender para montar, parametrizar e evoluir a árvore GN. O agente lê o estado da árvore e propõe scripts Python que o designer executa manualmente no Text Editor. O agente nunca é visto pelo profissional de saúde.

**O que não é:** produto final. O agente é o martelo, não a casa.

### Produto B — O painel paramétrico (produto final)

**Quem usa:** o ortesista ou terapeuta ocupacional que atende pacientes.

**O que é:** um painel de sliders e campos de medida dentro do Blender (ou fora, eventualmente), sem chat, sem IA visível, sem código. O profissional entra medidas clínicas (comprimento de antebraço, ângulo de punho, etc.) e o sistema GN parametrizado pelo Produto A gera e ajusta a órtese automaticamente.

**O que não é:** um wrapper do agente. O profissional nunca interage com o Claude nem vê scripts Python.

### Consequência para prioridades

- Toda melhoria de UX no agente (Produto A) serve o designer, não o paciente.
- A qualidade do contexto que o agente tem sobre a árvore GN é a métrica mais importante — ela determina a qualidade dos scripts que constroem o Produto B.
- A pergunta "o profissional de saúde quer entender o que o agente está fazendo?" não se aplica: o profissional nunca vê o agente.
- O critério de sucesso do Produto A é: "o designer consegue parametrizar completamente a árvore GN com ajuda do agente, sem precisar escrever Python manualmente".

---

## O que é este projeto

Addon Blender que embute um agente Claude como copiloto de Geometry Nodes para projetos de órteses. O designer conversa num painel lateral do Viewport 3D; o agente lê árvores GN e propõe scripts Python que o designer executa manualmente. O objetivo final é um sistema GN completamente parametrizado que o profissional de saúde usa via painel de parâmetros, sem nenhuma interação com o agente.

**Estado atual da árvore:** ~80 nós (atualizado 2026-04-30), objetivo declarado 400–500 nós. O sistema precisa escalar para isso.

---

## Estrutura de arquivos

> **Fonte de verdade do fluxo vivo:** `docs/refactor_handoff/LIVE_FLOW.md`. A árvore "histórica" abaixo está mantida apenas como contexto de histórico do refactor — vários arquivos listados não existem mais em `master` desde o slim refactor. **Não usar como referência operacional.**
>
> **Removidos / não existem mais no addon:** `agent_runtime.py`, `handlers.py` (raiz), `runtime_dispatch.py`, `tools.py` (raiz), `skill_router.py`, `runtime_agent_loop.py`, `runtime_api_client.py` (movido para `core/api_client.py`), `runtime_state_sync.py`, `session_store.py` (legacy), `simulator_mapper.py`, `knowledge_updater.py`, `execution/dispatcher.py`, `runtime/handlers/` (subpasta inteira), `runtime/staged_payload.py`, `runtime/gn_targeting.py`, `runtime/state_machine.py`, `runtime/handlers/_agent_loop.py`, `runtime/handlers/drafting.py`, `runtime/handlers/greeting.py`, `handler/_drafting_support.py`.
>
> **Superfície viva atual (2026-05-13):**
>
> - `blender_addon/core/` — `runtime.py` (AgentRuntime), `agent_loop.py`, `api_client.py`, `tool_policy.py`
> - `blender_addon/handler/` — `workspace.py` (entry point único `handle(ctx, goal_mode)`), `draft_*` (state/context/prompt/response/runtime/finalize/policy), `feedback*`, `prompt.py`
> - `blender_addon/runtime/` — `core.py` (Runtime — Phase 2), `router.py` (`infer_turn_intent`), `pending_decision.py`, `routing_obs.py`, `prompt_builder.py`, `tree_renderer.py`, `state_ops.py`
> - `blender_addon/tools/` — façade `handlers.py:HANDLERS` + módulos reais `draft.py`, `reads.py`, `edits.py`, `execution.py`, `query.py`, `snapshots.py`, `structural.py`, `tree_analysis.py`, `schemas.py`, `client.py`, `server_dispatch.py`
> - `blender_addon/session/` — `schema.py`, `store.py`, `chat_store.py`, `baseline.py`, `history.py`, `session_state_store.py`
> - `blender_addon/ui/` — `panel.py`, `panel_chat_turn.py`, `panel_runtime.py`, `panel_workspace.py`, `cycle_operators.py`, `cycle_state.py`, `chat_session.py`, `chat_operators.py`, `operators.py`, `advanced.py`, `screenshot.py`, `_helpers.py`
> - Topo do addon: `__init__.py`, `server.py` (socket bridge), `capture.py`, `safety_policy.py`, `operation_journal.py`, `snapshot_manager.py`, `model_policy.py`, `project_paths.py`, `runtime_planning.py`, `fast_path.py`, `text_utils.py` (helpers NLP consolidados, 2026-05-13)
>
> **Pendências grandes em aberto (não tocadas):** convergência `Runtime`/`AgentRuntime` (Phase 3), fatiamento adicional de `tools/server_dispatch.py` (~1754 linhas).

```
blend_IA_ort/
├── blender_addon/          ← addon instalável no Blender
│   ├── __init__.py         ← registro: importa ui + server
│   ├── agent_runtime.py    ← orquestrador de turno (AgentRuntime)
│   ├── capture.py          ← snapshots de cena e GN
│   ├── handlers.py         ← handlers Blender-side (execute_code, captura, etc.)
│   ├── knowledge_updater.py← aprendizado automático via claude-haiku (CONGELADO — ver abaixo)
│   ├── operation_journal.py← audit trail JSONL (runtime/journal/sessions/)
│   ├── safety_policy.py    ← gate de segurança para chamadas de ferramenta
│   ├── server.py           ← TCP bridge Blender (porta 65432)
│   ├── session_store.py    ← persistência legacy flat dict (schema 0.2, transitório)
│   ├── simulator_mapper.py ← mapeamento de payload de simulador para GN
│   ├── skill_router.py     ← roteamento de skills via runtime_dispatch
│   ├── tools.py            ← schemas de ferramentas + cliente socket
│   ├── runtime_dispatch.py ← dispatcher principal de ferramentas Blender
│   ├── runtime_planning.py ← constantes (MUTATION_TOOLS, FOCAL_READ_TOOLS) e helpers
│   ├── runtime_agent_loop.py← loop de tool-use (truncações aqui — ver seção abaixo)
│   ├── runtime_api_client.py← cliente Anthropic com retry logic
│   ├── runtime_state_sync.py← sincronização de estado pós-ferramenta
│   │
│   ├── runtime/            ← roteador + máquina de estados + handlers de turno
│   │   ├── core.py         ← Runtime class (session store, dispatcher, journal)
│   │   │                      journal.start_session() é adiado até blend_path resolvido
│   │   ├── router.py       ← TurnRouter: classifica mensagem em turn_class
│   │   ├── state_machine.py← execução de estado (idle→reading→drafting→failed→halted)
│   │   ├── routing_obs.py  ← observabilidade: infere turn_intent e session_state sem LLM
│   │   │                      loga routing_observation no journal (shadow mode)
│   │   ├── staged_payload.py← gerenciamento de draft de script entre turnos
│   │   ├── gn_targeting.py ← resolução de alvo GN canônico
│   │   ├── state_ops.py    ← operações puras sobre estado flat
│   │   ├── prompt_builder.py← instrução contextual por turn_class
│   │   └── handlers/       ← handlers ativos (consolidados)
│   │       ├── workspace.py    ← Onda 4c: unified workspace; inquiry + goal modes de draft entram aqui
│   │       ├── _agent_loop.py  ← deprecated/compat: helpers de discovery/baseline durante 4c
│   │       ├── drafting.py     ← utilitários/pipeline legado + state_control + execution_feedback (limpeza final pendente)
│   │       └── greeting.py     ← saudações e turnos triviais
│   │
│   ├── session/            ← schema V1 estruturado (destino final de persistência)
│   │   ├── schema.py       ← Session, ExecutionState, BaselineWorkspace, UIState, etc.
│   │   ├── store.py        ← SessionV1Store (JSON, runtime/sessions_v1/)
│   │   │                      arquivos inválidos/truncados → archive/quarantine/
│   │   │                      save() exclui history.messages do JSON
│   │   │                      load() hidrata messages do JSONL (migra automaticamente)
│   │   ├── chat_store.py   ← ChatHistoryStore (JSONL, runtime/chat_history/)
│   │   │                      append-only, uma linha JSON por mensagem
│   │   │                      escrito antes do save_v1_session() em cada turno
│   │   ├── baseline.py     ← BaselineBuilder + compute_tree_signature
│   │   │                      Onda 4b: drafting.py reconstrói baseline a partir de structural_memory
│   │   │                      Pré-4c: prepare_draft_context preserva marker.node_names/links no resumo
│   │   └── history.py      ← BoundedHistory (últimas N mensagens, in-memory)
│   │
│   ├── execution/          ← dispatcher Python-side
│   │   └── dispatcher.py   ← dispatch_tool(), process_screenshot_result()
│   │
│   ├── knowledge/          ← retriever de knowledge condicional
│   │   ├── corpus.py       ← KnowledgeCorpus (lê knowledge/domain/, skills/, recipes/)
│   │   └── retriever.py    ← seleciona items relevantes por turn_class + topics
│   │
│   └── ui/                 ← painel Blender
│       ├── panel.py        ← painel principal + todos os operadores
│       ├── chat_session.py ← _ChatSession + SESSION singleton
│       ├── screenshot.py   ← captura de screenshot (PowerShell + .NET no Windows)
│       ├── advanced.py     ← sub-painel de debug
│       └── _helpers.py     ← utilitários sem bpy
│
├── knowledge/              ← corpus de conhecimento do agente
│   ├── domain/             ← geonodes_node_reference.md, geonodes_ortese.md, etc.
│   ├── skills/             ← gn_diagnosis.md, gn_mutation.md, gn_navigation.md
│   └── recipes/            ← padrões reutilizáveis
│
├── docs/                   ← documentação de arquitetura
│   ├── SLIM_REFACTOR_PLAN.md   ← plano de execução desta branch
│   ├── repair_conversation_loop.md ← schema PendingUserDecision + acceptance tests
│   ├── draft_flow_audit.md     ← mapa da pipeline atual com line numbers
│   └── state_inventory.md      ← catálogo de fontes de estado
├── contracts/              ← schemas JSON de referência
├── legacy/                 ← histórico de desenvolvimento (não é runtime)
│
├── server.py               ← servidor MCP externo (FastMCP, alternativo ao addon)
├── blender_connection.py   ← cliente TCP para o bridge Blender
├── mcp_policy.py           ← helpers de política para o servidor MCP
└── CLAUDE.md               ← este arquivo
```

---

## Fluxo de runtime: prompt → resposta

> ✅ **Seção atualizada para refletir o estado pós-slim-refactor (2026-05-31).** Todos os módulos abaixo existem e estão rastreados. Fluxo detalhado com nomes de função em `docs/refactor_handoff/LIVE_FLOW.md`.

```
[Usuário digita no painel]
        ↓
ui/panel_chat_turn.py: _send_user_message()
  - grava mensagem no JSONL via chat_store.append()
  - lança thread background → _run_chat_turn()
        ↓
core/runtime.py: AgentRuntime.run_turn()
  1. Carrega V1 session via runtime/core.py: Runtime.v1_session_for(blend_path)
     └── journal.start_session() disparado na 1ª vez com blend_path real
  2. Reset por turno (pending_draft_action, phase guard)
  3. Resolve pending_decision se houver → runtime/pending_decision.py
  4. Tenta fast_path — fast_path.py try_fast_path()
     ├─ FP4: draft_confirmation  (draft pendente, sem LLM)
     ├─ FP1: greetings           (respostas fixas)
     ├─ FP2: help/capability     (texto estático)
     └─ FP3: simple reads        (get_node_context direto)
     Se hit → retorna imediatamente
  5. infer_turn_intent() → (turn_class, goal_mode)
     └── runtime/router.py (4 regras estruturais)
  6. Observabilidade: routing_obs.py (shadow-only, sem efeito no dispatch)
  7. handler/workspace.py: workspace.handle(ctx, goal_mode)
        ↓
handler/workspace.py: handle(ctx, goal_mode)
  - GoalConfig por goal_mode (inquiry / diagnose_only / focal_correction / functional_expansion / feedback_fix)
  - Lê draft atual, injeta render da árvore, reconstrói BaselineWorkspace
  - ctx.call_agent_loop(system_prompt, tools)
        ↓
core/agent_loop.py: agent_loop()
  - loop Anthropic API com tool use
  - resultados truncados por ferramenta (ver seção "Truncamentos")
  - cada tool_use_block → dispatch_tool_raw() → tools/client.py call_blender_socket()
        ↓
tools/client.py: call_blender_socket()  [TCP localhost:65432]
        ↓
blender_addon/server.py (Blender): runtime_tool_call
  → tools/server_dispatch.py: RuntimeDispatcher.execute()
  → tools/{draft.py, reads.py, edits.py, execution.py, query.py, ...}
        ↓
core/runtime.py: AgentRuntime.run_turn() (continuação)
  8. _finalize_turn(): adiciona mensagem assistant ao histórico
  9. chat_store.append() + fsync (JSONL)
 10. store.save() (V1 session JSON, write atômico)
 11. Retorna response_text → SESSION.messages → redraw do painel
```

---

## Estado real do contexto: o que o LLM vê (e o que não vê)

**Diagnóstico histórico (pré-4b, 2026-04-29):** O agente operava quase cego à árvore GN que deveria modificar.

**Status atual (2026-04-30):** Onda 4.E foi validada no Blender via journal. O agente injeta render compacto da árvore em perguntas factuais e turnos de draft, reconstrói/usa `BaselineWorkspace`, preserva `marker.node_names`/`marker.links` no resumo do `prepare_draft_context`, e registra falha visível quando a recuperação de memória estrutural falha. Em um primeiro turno pós-reabertura, o draft começou com contexto de árvore reaproveitado de memória estrutural persistida; isso é comportamento aceito mesmo quando o evento literal `build_tree_structural_memory` não aparece.

### O que chega ao prompt hoje

| Fonte | O que entra | Limite |
|---|---|---|
| `tree_prompt_render_injected` / tree renderer | Nomes de nós, frames/regiões, sockets de interface, links, parâmetros e marker counts | ~3100 chars no run validado (`render_chars=3104`) |
| `BaselineWorkspace` | Structural summary persistida e assinatura da árvore, reconstruída a partir de structural memory | Persistente por sessão V1 |
| `_compact_structural_memory()` | Fallback compacto (`tree_name`, contagens, regiões, parâmetros, node groups) | 1400 chars |
| `prompt_builder._build_focus_block()` | Resumo de foco/baseline quando disponível | compacto |
| Knowledge bundle | Itens selecionados pelo retriever | 600 chars/item (`prompt_builder.py:189`) |
| Draft atual | `state.content[:5000]` | 5000 chars (`drafting.py:1386`) |

**O que ainda exige cuidado:**
- O render da árvore chega ao prompt nos caminhos validados, mas ainda há caminhos legados/fallback que usam `_compact_structural_memory()`.
- O tamanho da árvore atual (~80–103 nós nos runs recentes) ainda está abaixo da meta de 400–500 nós; a estratégia precisa continuar escalando sem voltar a truncar nomes críticos.
- Perguntas factuais podem chamar ferramentas focais (`find_tree_nodes`) quando o modelo quer confirmar nomes; isso é aceitável, desde que o system prompt já tenha recebido o render ou a falha seja registrada.

### BaselineWorkspace depois da Onda 4b

`session/baseline.py:44` agora é chamado por `runtime/handlers/drafting.py` quando há `structural_memory` fresca no turno. Na sessão `sess-20260429T143019Z-e909c754`, o baseline foi reconstruído para `Biomodelo` com `node_count=80`, `stale=false` e assinatura `ba45f7da231eb0d9`. Pré-4c corrigiu o caso em que o baseline recebia regiões/parâmetros, mas perdia `marker.node_names` e `marker.links`.

### Mecanismos de memória

1. **`BaselineWorkspace`**: ativo; reconstruído a partir de `tree_structural_memory` e usado como memória técnica persistente.
2. **`tree_structural_memory`**: fonte rica do render compacto; pode vir de leitura fresca ou memória estrutural persistida.
3. **`structural_index`**: ainda secundário/irregular; não deve ser a única fonte de nomes/sockets.
4. **`Simulate Bridge Failure`**: flag de debug em `UIState` V1 para validar logs de falha de recuperação estrutural. Nunca deixar ligada após teste.

### O que existe e é rico (mas não usado adequadamente)

- `capture_node_trees_snapshot()` (`capture.py:337`): snapshot completo com nós, links, interface, bindings
- `build_tree_structural_memory` (`tools/structural.py`): `major_regions[≤80]` + `key_nodes[≤12]`/região, `key_joins`, `key_outputs`, `parameters`, `structural_hash` — função agora vive em `tools/structural.py` (antigo `runtime_dispatch.py:1279`, deletado)
- `MAX_NODES_PER_GROUP=256` (`capture.py:25`): será ultrapassado ao atingir 400–500 nós

**Caminho validado na Onda 4.E:** render compacto do snapshot/structural memory injetado no system prompt de `context_inquiry` factual e `draft_workspace`, com fallback e falha visível via journal quando a memória estrutural não está disponível.

---

## Truncamentos: onde o dado é cortado

> ⚠️ **`runtime_agent_loop.py` foi deletado no slim refactor.** A lógica de truncamento está agora em `core/agent_loop.py`. Os valores abaixo refletem o estado validado (4d); verificar `core/agent_loop.py` para a implementação atual.

Constantes de truncamento (migradas de `runtime_agent_loop.py` → `core/agent_loop.py`):

```python
_MAX_TOOL_RESULT_CHARS = 6000   # ferramentas gerais
_HEAVY_READ_TOOLS = {           # ferramentas com corte mais agressivo
    "get_local_subgraph_context",
    "classify_tree_phases", "map_clinical_parameter_roles",
    "interpret_orthosis_tree_logic", "get_scene_summary", "get_gn_hosts",
    "analyze_gn_state", "analyze_scene",
}
_MAX_READ_RESULT_CHARS = 4000   # ferramentas em _HEAVY_READ_TOOLS
```

**Status 4d:** `build_tree_structural_memory` saiu de `_HEAVY_READ_TOOLS`; a ferramenta mais rica sobre a árvore agora usa o teto geral de 6000 chars.

**Status 4d:** compressão de tool_use preserva argumentos semânticos dos draft tools, e `read_script_draft` duplicado em `draft_workspace` é bloqueado quando o pipeline já leu o draft no início do turno.

---

## Política de economy_retry: o antagonista em REPAIRING

**Quando ativa:** estado `REPAIRING`, `economy_retry=True`.

**O que bloqueia:**
- Todos os broad reads (`list_tree_nodes`, `build_tree_structural_memory`, `get_scene_summary`, etc.): bloqueio **incondicional** (implementado em `core/runtime.py` — antigo `agent_runtime.py:1235-1236`, deletado)
- Focal reads (`find_tree_nodes`, `get_node_context`, etc.) agora têm orçamento mínimo em `economy_retry`: `focal_budget=3` sempre que o retry econômico está ativo (implementado em `handler/workspace.py` — antigo `drafting.py:1476`, deletado)

**Caso de falha documentado** (run `run-20260428T201426Z-0894ae38.jsonl`): usuário pediu "confirma os nomes dos nós antes de escrever"; estado=REPAIRING+economy_retry; `list_tree_nodes` BLOCKED; `find_tree_nodes` BLOCKED; 3 rounds exauridos; resultado=`interrupted`; zero writes.

**Correção implementada (Onda 4a, 2026-04-29):** em REPAIRING/economy_retry, `focal_budget` mínimo de 3, independente de cobertura existente. Um agente que não pode verificar nomes de nó antes de reescrever nunca vai sair do estado REPAIRING.

---

## Regras do agente

- Responde em português brasileiro, conciso
- Minimiza chamadas de API agressivamente **mas não a ponto de bloquear leituras necessárias em REPAIRING**
- Prefere `get_node_context` a leituras amplas de árvore
- Se incerto sobre tipo de nó: chama `query_node_types` primeiro (local, sem custo de API)
- Para propor mutações GN: usa `write_script_draft` — **nunca** chama `execute_code` autonomamente
- `execute_code` e `make_plan` estão **bloqueados no fluxo automático** — o usuário os dispara manualmente quando quer executar um draft
- Scripts Python para GN devem usar `socket.identifier` para inputs/outputs de grupo; para sockets internos de nó, usar o nome (`socket.name`) — `capture.py` captura `identifier` apenas para interface Group Input/Output

### Invariante pós-falha (atualizado 2026-05-05)

**Falha de execução não é permissão automática para reescrever.**

Quando o usuário reporta falha, reverte a cena, ou envia feedback negativo:

1. O agente **deve** recuperar o draft que falhou (via `draft_history`, não apenas Text Editor).
2. O agente **deve** montar evidência concreta do draft falho quando possível: nós tocados, sockets alterados, links criados/removidos, leituras de interface e conflitos com `structural_memory`.
3. O agente **deve** raciocinar sobre a falha em forma conversacional — sintoma observado, hipótese mais provável, evidência disponível, limitações do diagnóstico — sem formato de seções obrigatório.
4. O agente **deve** propor estratégias (≥2) antes de reescrever.
5. O agente **deve** aguardar aprovação explícita do usuário antes de escrever novo draft.
6. O agente **não pode** chamar `write_script_draft` no mesmo turno em que recebeu o feedback de falha.

**Tokens que NÃO liberam escrita sozinhos:** `draft`, `script`, `código`, `corrigir`, `salvar` sem imperativo claro.

**O que libera escrita:** imperativo explícito ("reescreve", "corrige agora", "segue com a opção A") ou aprovação de estratégia proposta. A aprovação deve ser resolvida por correspondência com as opções oferecidas (`PendingUserDecision`), não por regex de vocabulário fixo.

**Regra arquitetural de decisão pendente:** o helper `set_pending_decision()` é a única forma válida de emitir uma pergunta de decisão. Handlers não devem escrever manualmente perguntas A/B no texto sem registrar a entidade operacional correspondente. Nenhum handler pode terminar com pergunta de escolha A/B, confirmação de escrita, autorização de leitura focal, esclarecimento de escopo ou direção de reparo sem materializar `PendingUserDecision`. Se a resposta contém opções A/B mas não passa por esse helper, isso é bug.

**Status implementado (com ressalvas):** `handle_execution_feedback()` usa `_read_failed_draft_info()` para priorizar o arquivo arquivado; bloqueia reescrita automática no turno de falha; gera evidência estática (nós/sockets tocados, conflitos semânticos com `structural_memory`); registra `STRATEGY_PROPOSED` quando há opções válidas.

**Status das falhas Wave 5.C (atualizado 2026-05-31):**
- ⚠️ **Pendente:** `STRATEGY_PROPOSED`/`REPAIRING` — o estado conversacional tem dois campos espelhados (`session_state` e `post_failure_state`) que recebem os mesmos valores em paralelo; desincronização pode fazer o turno seguinte chegar em estado errado. Ver seção "Dívida técnica atual" abaixo.
- ⚠️ **Pendente:** O LLM falha no contrato de cabeçalhos exatos; `_fallback_post_failure_diagnosis()` pode disparar para toda falha, produzindo resposta genérica. A invariante de segurança é comportamental (agente não chama `write_script_draft` no turno de falha), não tipográfica.
- ✅ **Resolvido:** Aprovações por nome de opção ("Caminho B", "Opção A") — `_match_option()` em `runtime/pending_decision.py` agora trata ordinais ("primeiro", "segundo", "1", "2"), palavras de estratégia ("caminho", "opção", "estratégia") e letras únicas com contexto. O router (Regra 1) reconhece `pending_status=="answered"` e roteia para `DRAFT_WORKSPACE/focal_correction`.

Ver `docs/repair_conversation_loop.md` para a direção arquitetural e o schema `PendingUserDecision`.

---

## Ferramentas disponíveis para o agente

| Ferramenta | Descrição |
|---|---|
| `write_script_draft` | Propõe script Python/bpy para o usuário revisar e executar |
| `query_node_types` | Introspecção local dos tipos de nó GN disponíveis (sem custo API) |
| `get_scene_summary` | Estado global da cena |
| `get_gn_hosts` | Lista objetos com modificadores GN |
| `get_node_context` | Contexto local de um nó e vizinhança (preferido) |
| `get_selected_nodes_context` | Contexto dos nós selecionados |
| `get_active_frame_context` | Contexto de um frame ativo |
| `get_local_subgraph_context` | Subgrafo focado por lista de nós ou centro |
| `get_changes_since_last_turn` | Diff focado desde o último turno |
| `get_tree_parameters` | Valores de inputs do modificador GN |
| `analyze_scene` | Diagnóstico compacto de cena |
| `analyze_gn_state` | Diagnóstico compacto de estado GN |
| `capture_screenshot` | Captura visual do viewport + análise multimodal |
| `apply_simulator_payload` | Aplica valores de simulador nos parâmetros GN |
| `execute_code` | **Bloqueado no fluxo automático.** Só executável pelo usuário manualmente. |
| `make_plan` | **Bloqueado no fluxo automático.** Legado — será removido. |

---

## Persistência de sessão

Dois stores ativos (o store legacy foi removido no slim refactor):

| Store | Arquivo | Conteúdo |
|---|---|---|
| V1 (SessionV1Store) | `runtime/sessions_v1/<hash>.session.json` | identity, focus, execution_state, baseline_workspace, ui_state, session_memory — **sem messages** |
| ChatHistory (ChatHistoryStore) | `runtime/chat_history/<session_id>.jsonl` | mensagens visíveis, append-only, uma linha JSON por mensagem |

> **Legacy store removido:** `session_store.py` (flat dict, schema 0.2) foi deletado. Sessões antigas em `runtime/sessions/` ainda existem localmente mas não são mais lidas no hot path. Import só via `store.import_legacy_sessions_explicit()` — nunca automático.

Comportamentos importantes:
- `history.messages` **não** são mais gravados no session JSON — vivem apenas no JSONL
- Sessões antigas com messages no JSON são migradas para JSONL automaticamente na primeira carga (idempotente)
- Chat é persistido imediatamente ao receber cada mensagem — antes do `save_v1_session()`
- Botão Clear apaga o JSONL além de limpar memória
- Arquivos de sessão inválidos/truncados são movidos para `runtime/sessions_v1/archive/quarantine/`
- Import legacy só via `import_legacy_sessions_explicit()` — **nunca** no hot path de load
- `runtime/` é gerado automaticamente pelo addon e está no `.gitignore`

---

## Como validar que o sistema está funcionando

Após qualquer alteração no addon, enviar esses prompts no painel do Blender:

### Testes de linha de base

1. `qual o estado atual da cena?` → deve retornar resumo via `get_scene_summary` + `get_gn_hosts`
2. `mostra o contexto do nó <nome_de_nó_existente>` → deve retornar via `get_node_context`
3. Fechar o Blender, reabrir o mesmo `.blend`, abrir o painel → conversa anterior deve aparecer

### Testes específicos para Onda 4.E (validados em 2026-04-30)

4. Pergunta factual: `qual o nome do nó que controla a escala do metacarpo?` → journal deve conter `tree_prompt_render_injected` com `marker_node_names_count > 0`.
   - Run validado: `run-20260430T191720Z-bb9dd970`, `tree_name=Biomodelo`, `node_count=80`, `marker_node_names_count=80`.
5. Primeiro draft pós-reabertura: fechar/reabrir Blender e enviar `escreve um draft para parametrizar a escala do metacarpo` → journal deve conter `tree_prompt_render_injected` antes da escrita do draft e `baseline_workspace_rebuilt`.
   - Run validado: `run-20260430T194733Z-371620ea`, `tree_prompt_render_injected`, `baseline_workspace_rebuilt`, `script_draft_write_succeeded`.
   - Observação: esse caminho pode reaproveitar memória estrutural persistida em vez de chamar `build_tree_structural_memory`; isso é aceito se o render de árvore entrou no turno antes da escrita.
6. Falha visível de memória/bridge: em `Advanced / Debug`, marcar `Simulate Bridge Failure`, clicar `Apply Flags`, enviar a pergunta factual e conferir `structural_memory_recovery_failed` com `reason`.
   - Run validado: `run-20260430T202014Z-cd0a8fd5`, com `simulate_bridge_failure_active` e `structural_memory_recovery_failed.reason` preenchido.
   - Sempre desmarcar `Simulate Bridge Failure` e clicar `Apply Flags` após o teste.

### Testes pós-falha (parcialmente funcionando — ver Wave 5.C)

7. Gerar um draft, clicar `Abrir Draft`, depois `Rodar Draft`, e reportar falha com descrição visual como `nada aconteceu` ou `mexeu no alvo errado`.
   - **Esperado:** journal deve conter `script_draft_execution_feedback` e `script_draft_execution_diagnosis`; agente **não** deve chamar `write_script_draft` neste turno.
   - **Verificar no journal:** `failed_draft_source=draft_history` (priorizou arquivo arquivado, não apenas Text Editor); `post_failure_state=STRATEGY_PROPOSED`.
   - **Bug conhecido:** `STRATEGY_PROPOSED` é imediatamente sobrescrito para `REPAIRING` no mesmo run pelo FSM — conferir `state_transition` logo após `script_draft_execution_diagnosis`.

8. A resposta de falha deve: (a) citar evidência concreta do draft falho — nó/socket tocado, link criado/removido, ou conflito semântico com `structural_memory`; (b) propor uma direção operacional de reparo, ou alternativas apenas quando isso for realmente útil; (c) encerrar com pergunta ao designer quando precisar de decisão. **Não há formato de seções obrigatório — o teste é comportamental.**
   - **Sinal de regressão:** se a resposta for idêntica para falhas diferentes (template genérico), `_fallback_post_failure_diagnosis()` disparou. Investigar se `diagnosis_contract_satisfied=true` no journal — se sim, o fallback está mascarando a falha real do LLM.
   - **Sinal de evidência viva:** journal deve conter `static_evidence_available=true` e `static_evidence_touched_nodes` não-vazio quando o draft tocou nós identificáveis.

9. Ao verificar `static_evidence_mismatches` no journal: se não-vazio (ex: "draft claims no falanges changed, but touched nodes/frames include falange-related names"), a resposta do agente **deve** incorporar esse conflito como hipótese central ou direção de reparo. Não basta citar `operation_counts`; não basta dizer genericamente "pode ser problema de sockets ou links". Se o LLM não usar o mismatch real, o fallback deve rodar, e o fallback também deve usar esse mismatch.

10. Toda resposta com opções A/B deve materializar `pending_user_decision` via `set_pending_decision()` antes de retornar.
    - **Esperado pós-Wave 5.C:** acceptance tests cobrem que nenhuma resposta com opções A/B termina sem `pending_user_decision.status="pending"`.
    - **Bug:** opção A/B no texto sem entidade operacional correspondente.

11. Depois da resposta diagnóstica, enviar `segue com a opção A e reescreve` (incluindo verbo de escrita explícito).
    - **Esperado atual (frágil):** funciona se a mensagem contiver verbo explícito de escrita (ex: "reescreve") — reconhecido como `draft_refinement` → `focal_correction` → `write_allowed=true`.
    - **Falha conhecida:** `segue com a opção A` ou `Caminho B` sozinhos não são reconhecidos — caem em `diagnose_only` (write_allowed=false) e não geram draft.
    - **Esperado pós-Wave 5.C:** qualquer referência ao nome da opção oferecida (`PendingUserDecision.match(options)`) deve liberar escrita, independente do vocabulário.

### Verificar no filesystem

- `runtime/chat_history/<session_id>.jsonl` → criado e contém as mensagens
- `runtime/sessions_v1/<hash>.session.json` → campo `history.messages` deve ser `[]` (vazio)
- `runtime/journal/sessions/<sess-id>.jsonl` → evento `goal_start` com `blend_file` não-vazio
- `runtime/sessions_v1/archive/quarantine/` → arquivos inválidos movidos aqui (se houver)

---

## Dívida técnica atual

> Esta seção documenta limitações e pendências reais identificadas pós-slim-refactor. Não são bugs críticos; são itens a considerar nas próximas ondas.

### Dois runtimes coexistindo (Phase 3 pendente)

`AgentRuntime` (`core/runtime.py`, ~1908L) e `Runtime` (`runtime/core.py`, ~1274L) são dois objetos distintos com ciclos de vida diferentes: o primeiro orquestra Python-side (chama a API Anthropic), o segundo é Blender-side (gerencia sessão e despacha ferramentas via socket). A convergência está documentada como Phase 3 do slim plan e ainda não foi feita. **Não fundir sem validação smoke no Blender.** Referência: `docs/SLIM_REFACTOR_PLAN.md §Phase 3`.

### Redundância de estado de autorização

`ExecutionState` tem múltiplos campos que representam o mesmo conceito de "aprovação do usuário" e ficam espelhados manualmente:
- `session_state` e `post_failure_state` recebem os mesmos valores (`STRATEGY_PROPOSED`, `STRATEGY_APPROVED`) em paralelo
- `approved_strategy_label`, `approved_strategy_prompt`, `pending_draft_action` e o objeto `pending_user_decision.answered_with` rastreiam redundantemente o estado de aprovação

Desincronização entre esses campos é a causa-raiz do bug "STRATEGY_PROPOSED colapsa para REPAIRING". Solução futura (Onda 5): eliminar `post_failure_state` como campo separado; usar apenas `session_state` + `pending_user_decision`.

### Fragilidade de roteamento em português

`infer_turn_intent()` (`runtime/router.py:146`) usa lista fixa de prefixos de verbos PT para detectar imperativo de escrita (`escrev`, `faz`, `mud`, `cri`...). Riscos conhecidos:
- **Falso positivo:** "faz sentido?" casa o prefixo `faz` e pode ser roteado como imperativo de escrita
- **Semântica inconsistente:** "muda a abordagem" durante uma `PendingUserDecision` é tratado como negação/cancelamento (`pending_decision.py:291`), mas fora da decisão pendente é roteado como escrita
- **Aprovação como pergunta:** "pode seguir com a opção A?" contém `?` → tratado como pergunta → decisão fica pendente em vez de ser aprovada

A solução arquitetural correta (documentada em CLAUDE.md "O que NÃO fazer") é depender de `PendingUserDecision._match_option()`, não ampliar prefixos. O problema de falso-positivo fora de decisão pendente exige refinamento do router (Onda 4 futura).

### Acoplamento Anthropic (multi-LLM é Onda 6 futura)

O sistema está acoplado ao SDK Anthropic em três pontos:
1. Instâncias `anthropic.Anthropic(api_key=...)` em `core/runtime.py` e `ui/panel_chat_turn.py`
2. IDs de modelo hardcoded em `model_policy.py` (`claude-haiku-4-5`, `claude-sonnet-4-6`)
3. Formato de mensagens/tool-use Anthropic em `core/api_client.py` (`messages.create/stream`, `cache_control: ephemeral`)

O ponto de costura natural para abstração multi-LLM é `core/api_client.py` — já é um adaptador fino. **Não alterar sem uma implementação de provider fake nos testes.**

### Diretório `skills/` ausente

`tools/server_dispatch.py` tenta importar `skills.scene_context_inspector` e `skills.gn_scene_state_interpreter`. Não há `skills/` no repositório. Há fallback local (`_build_local_gn_report`, `_build_local_scene_report`) — o sistema não quebra, mas a funcionalidade "rica" de relatórios degrada silenciosamente. O README de instalação futuro deve documentar que `skills/` é um diretório opcional a apontar no campo "Project Root Path".

### Projeto não está pronto para GitHub público

Falta para publicação: README de topo, instruções de instalação (incluindo `pip install anthropic` no Python do Blender), `requirements.txt` ou equivalente, `LICENSE`, e exemplos de uso. Ver **Onda 2** do plano de refatoração.

---

## O que NÃO fazer

### Arquitetura

- Não recriar `skill_router.py` — foi **deletado** no slim refactor; o roteamento é feito por `runtime/router.py:infer_turn_intent()`
- Não recriar `safety_policy.py` separado — a política vive em `core/tool_policy.py` (`BLOCKED_PRODUCT_TOOLS`, `DraftAttemptContract`)
- Não usar MCP como canal principal — socket direto (porta 65432) é o padrão
- Não criar Verifier como classe separada
- Não adicionar mais listas de vocabulário fixo a `infer_turn_intent()` para reconhecer aprovações — a solução é `PendingUserDecision._match_option()` (já implementada), não ampliar prefixos de palavras
- Não emitir pergunta de decisão manualmente no texto. Usar `set_pending_decision()`; pergunta A/B sem `PendingUserDecision` é bug arquitetural, não detalhe opcional
- Não recriar `state_machine.py` — foi **deletado** no slim refactor; a máquina de estados está em `session/schema.py:SESSION_STATES` + `runtime/pending_decision.py`
- Não chamar `execute_code`, `make_plan` ou `apply_simulator_payload` automaticamente no loop do agente — são `BLOCKED_PRODUCT_TOOLS` (user-triggered)
- Não reintroduzir ferramentas GN atômicas (`create_node`, `connect_nodes`, `set_node_value`, etc.)
- Não exigir formato de seções exatas (Sintoma/Hipótese/Evidência/Confiança/Limitações/Opções/Pergunta) no prompt de diagnóstico pós-falha — a invariante de segurança é comportamental, não tipográfica

### Contexto / memória de árvore

- **Não** aumentar o `max_chars` de `_compact_structural_memory` sem substituir o que está dentro dela — 4000 chars do mesmo JSON comprimido não ajuda se ainda falta nomes de nó individuais
- **Não** ativar `BaselineBuilder.rebuild_from_summary()` sem antes ter um renderer que produza um `structural_summary` legível para o LLM — a assinatura SHA-1 é correta, mas o conteúdo importa mais
- **Não** injetar todo o knowledge em toda mensagem — o retriever seleciona contextualmente
- **Não** injetar o snapshot completo sem renderer — `capture_node_trees_snapshot()` é JSON enorme; precisa de um render seletivo antes de entrar no prompt
- **Não** usar `socket.name` para sockets de interface de grupos GN em scripts Python — usar `socket.identifier` (capturado em `capture.py` para Group Input/Output)

### Persistência / sessão

- Não importar legacy sessions no hot path de load — só via `import_legacy_sessions_explicit()`
- Não gravar `history.messages` no session JSON — campo deve permanecer vazio

### Economy retry

- **Não** endurecer ainda mais as regras de economy_retry sem antes resolver a injeção de árvore no prompt — o agente requer leituras porque o contexto é insuficiente, não por desperdício
- **Não** reduzir `focal_budget` a zero como padrão em REPAIRING — isso produz loops de `interrupted` sem entrega (run 0894ae38)

### knowledge_updater

- `knowledge_updater.py` foi **deletado** no slim refactor e não está mais rastreado no git. Não recriar sem uma decisão explícita de reativar o loop de aprendizado automático. Consequência: `knowledge/domain/learned_patterns.md` está **órfão** — ainda existe e o retriever o carrega, mas está estático (1 padrão); o mecanismo que o gerava foi removido. Para manter o arquivo útil, editar manualmente com padrões curados.

---

## Refactor em andamento

**~~Branch `slim-refactor`~~ CONCLUÍDO (2026-05-06 a 2026-05-31):** o plano de 7 fases substituiu ~10k linhas dos 4 módulos bloated por uma estrutura enxuta em `core/`, `handler/`, `tools/` e `ui/`. Ver `docs/SLIM_REFACTOR_PLAN.md` como referência histórica do plano. As Ondas 1–4 estão entregues; os módulos `tree_renderer`, `BaselineWorkspace`, `OperationJournal`, `ChatHistoryStore`, `snapshot_manager` foram preservados. Ondas 5 (parcial), 6 (Working Memory) e 7 (state machine formal) ficam adiadas para o futuro.

Ver `docs/repair_conversation_loop.md` para a frente de reparo conversacional pós-falha — direção arquitetural, falhas sistêmicas identificadas e schema de `PendingUserDecision`.

**Estado consolidado pós-merge (2026-05-31): Ondas 1–3 ✅ — Onda 4a–4d ✅ — Onda 4.E validada no Blender ✅ — Onda 5 UI parcial ✅ — Frente pós-falha Wave 5.C parcialmente resolvida 🔶 (aprovação de opções A/B resolvida ✅; espelhamento session_state/post_failure_state pendente ⚠️) — Working Memory e state machine formal adiados ⬜**

**Hotfix de UX (2026-04-29):** após teste manual frustrante no Blender, o painel passou a sanitizar blocos de código Python em mensagens finais do assistente e no histórico carregado. O roteador também reconhece "escreve um draft" / "escreve um script" como `draft_workspace`, evitando que pedidos de escrita caiam em `context_inquiry` e despejem código no chat.

### Ondas 1–3 (concluídas)

- **Onda 1**: quarentena, journal ancorado em blend_path, session_active espelhado
- **Onda 2a**: ChatHistoryStore JSONL, messages fora do session JSON — validado no Blender
- **Onda 2b**: routing_obs corrigido, shadow handler estendido, decisão de não implementar override de dispatcher
- **Onda 3**: journal por run_id, run_id/session_id propagados via socket, índices shardados, debug channel separado

### Onda 4 — Desbloqueio de contexto

Itens principais:

1. **4a — Desbloquear leituras focais em REPAIRING**: concluído em 2026-04-29. `focal_budget=3` mínimo em economy_retry, independente de cobertura. Testes unitários focados passaram.
2. **4b — Injetar árvore no prompt**: implementado em 2026-04-29 e validado em 2026-04-30. `runtime/tree_renderer.py` renderiza nomes, frames, sockets de interface, links e parâmetros; `prompt_builder.py` injeta baseline persistida; `drafting.py`/`workspace.py` injetam structural_memory fresca ou persistida e reconstroem `BaselineWorkspace`.
3. **4c — Unified workspace handler**: goal modes principais migrados em 2026-04-29. `workspace.py` criado com `GoalConfig`; `CONTEXT_INQUIRY` e `DRAFT_WORKSPACE` roteiam para `workspace.handle(ctx, goal_mode)`. `diagnose_only`, `focal_correction`, `functional_expansion` e `feedback_fix` executam pelo workspace reutilizando utilitários de `drafting.py`; `EXECUTION_FEEDBACK` permanece direto em `drafting.py` por enquanto.
   - Hotfix pós-validação Blender: `write_script_draft` agora encerra o loop após o primeiro sucesso mesmo quando o retorno vem no formato real do Blender (`block_name` + `version/char_count`), evitando múltiplas reescritas no mesmo turno.
   - Hotfix UX: diagnóstico de execução foi encurtado e instruído a não mostrar snippets/código no chat.
   - Hotfix smoke: "podemos tentar corrigir?" e similares agora entram como `focal_correction`; `write_script_draft` bloqueado também encerra o loop após o primeiro bloqueio, evitando repetição até round-limit.
   - Hotfix smoke 4d: diagnóstico read-only não deve terminar mudo no round-limit; o finalizador gera diagnóstico mínimo útil. Intenções explícitas de escrita ("escreva", "salve", "continua") entram como `focal_correction`, e mensagens indicando árvore alterada/revertida forçam refresh do contexto preparado.
   - Hotfix smoke 4d: em `DRAFT_WORKSPACE`, `pure_inquiry` volta a ser read-only (`diagnose_only`) quando não há pedido claro de escrita; pedidos explícitos de correção/escrita continuam como `focal_correction`.
   - Hotfix policy 4d: `get_tree_parameters` é permitido em `diagnose_only` sem `economy_retry`; o bloqueio de broad reads em `economy_retry` permanece inalterado.
4. **4d — Revisão de truncamentos**: implementado em código em 2026-04-29 e coberto pela validação 4.E em 2026-04-30. `_MAX_TOOL_RESULT_CHARS=6000`, `_MAX_READ_RESULT_CHARS=4000`; `build_tree_structural_memory` saiu de `_HEAVY_READ_TOOLS`; `get_scene_summary`/`get_gn_hosts` entraram como heavy reads. Compressão de tool_use preserva contexto dos draft tools e `read_script_draft` duplicado em `draft_workspace` é bloqueado quando o pipeline já carregou o draft.
5. **4.E — Validação Blender/journal**: concluída em 2026-04-30. Passaram: tree render no system prompt, draft pós-reabertura com contexto de árvore, e falha visível de recuperação estrutural com `reason`. Durante a validação foram corrigidos: roteamento de perguntas factuais em `drafting`, histórico contaminando inquiry, finalização muda em leitura/diagnóstico, retry automático após bloqueio semântico de `write_script_draft`, e flag `Simulate Bridge Failure` persistida no `UIState` V1.

Ver `docs/SLIM_REFACTOR_PLAN.md` §6 para critérios de saída mensuráveis por fase.

### Onda 5 — UX do ciclo de trabalho (em progresso, sessão 9)

**O que foi implementado (2026-05-01):**

- **4 estados do painel funcionando:** `idle` → `pending_user_execution` → `executing` → `awaiting_feedback` com operadores separados para cada transição. `_get_runtime_ui_state()` agora encaminha `work_cycle_phase`, `current_revision` e `draft_revision_count` ao painel (eram ignorados antes).
- **Snapshot manager:** `blender_addon/snapshot_manager.py` implementado. `BLEND_OT_execute_draft` chama `take_snapshot()` diretamente (não via socket — socket causava deadlock por chamar `execute_in_main_thread` do thread principal). `BLEND_OT_revert_snapshot` idem.
- **Fluxo de sucesso corrigido:** `BLEND_OT_result_success` não chama mais o agente. Antes disparava um turno que atingia round limit. Agora seta `idle` e adiciona mensagem local `"✓ Script vN aplicado com sucesso."` sem chamada ao Claude.
- **Fluxo de falha corrigido:** `handle_execution_feedback` não seta mais `pending_draft_action` automaticamente. O agente convida à discussão antes de reescrever, respeitando o fluxo colaborativo que o designer quer.
- **`pure_inquiry` em REPAIRING corrigido:** `_workspace_goal_mode` não força mais `focal_correction` quando o estado é REPAIRING e a intenção é leitura — evitava perguntas factuais de disparar reescrita imediata.
- **Router:** padrão `[RESULTADO]` (sucesso) removido — sucesso não vai mais ao agente. Padrão `[RESULTADO DE EXECUÇÃO]` (falha) mantido.

**Status revisado em 2026-05-04: fluxo "Enviar e Reverter"**

O fluxo combinado foi validado manualmente pelo usuário como suficiente para avançar: a UI permite reportar falha, reverter, escolher estratégia e gerar novo draft. A qualidade do diagnóstico ainda precisava melhorar, e por isso foi implementado o pacote de evidência estática pós-falha descrito em `docs/repair_conversation_loop.md`.

**Histórico do problema original: fluxo "Enviar e Reverter"**

O designer pediu um fluxo combinado: ao reportar falha, enviar o feedback ao agente para discussão E ao mesmo tempo reverter o Blender para o estado pré-script, tudo em um passo.

O problema fundamental: `restore_snapshot()` chama `bpy.ops.wm.open_mainfile()` que destrói todos os threads em background, incluindo o thread do agente processando o feedback. O agente nunca chega a responder.

**Tentativa implementada (`BLEND_OT_send_and_revert`):**
1. Envia feedback ao agente (thread background inicia)
2. Copia o snapshot sobre o `.blend` no disco imediatamente
3. Seta `_deferred_reopen_path` — não abre o arquivo agora
4. `_poll_runtime_redraw()` aguarda `SESSION.running == False` e só então chama `open_mainfile`

**Hipótese original de falha:** o reopen podia ocorrer antes que o JSONL do chat history fosse flushed ao disco pelo thread do agente. Quando o Blender recarregava, o histórico lido do JSONL podia não conter a resposta mais recente. Também podia haver race condition entre o save do `chat_store` e o `open_mainfile`.

**Plano considerado na época:**
- Garantir flush explícito do JSONL antes de `SESSION.running = False` ser observado pelo timer
- Ou: mostrar a resposta e oferecer botão manual "Reabrir arquivo revertido" — o designer decide quando reabrir, após ler a resposta

Naquele momento, o designer podia usar "Só Enviar" (feedback sem revert) e "Só Reverter" (revert sem feedback) separadamente.

**Atualização de código (2026-05-01, sessão 10):**
- `ChatHistoryStore.append()` agora faz `flush()` + `os.fsync()`.
- `SessionV1Store.save()` agora usa arquivo temporário + `replace()` atômico.
- `ui/panel.py::_run_chat_turn()` agora só seta `SESSION.running = False` depois que a resposta final já foi adicionada ao `SESSION`.
- O reopen deferido agora espera uma nova mensagem final do assistente no `SESSION` antes de chamar `open_mainfile()`.
- Teste novo: `tests/test_session_persistence_durability.py`.

**Status histórico:** a correção foi implementada em código e ficou aguardando validação manual no Blender.

**Correção adicional (2026-05-01, sessão 10):**
- Causa encontrada após teste manual: `_on_blend_load_post()` chamava `rt.clear_history()` depois do `open_mainfile()`.
- `AgentRuntime.clear_history()` apaga o JSONL persistido; portanto o reload do snapshot estava destruindo exatamente o histórico que deveria sobreviver.
- Adicionado `AgentRuntime.clear_runtime_context()`, que limpa apenas `_messages` e `_active_v1_session`.
- `_on_blend_load_post()` agora usa `clear_runtime_context()`; o botão Clear continua usando `clear_history(blend_path=...)` para apagar histórico quando o usuário pede explicitamente.
- Teste novo em `tests/test_foundation_stabilization.py`: `test_clear_runtime_context_does_not_clear_persisted_history`.

**Status histórico revisado:** o reload do snapshot não deveria mais apagar prompt, resposta do draft nem feedback persistidos. Em 2026-05-04, o fluxo foi considerado bom o suficiente para avançar para qualidade diagnóstica.

**Ajuste UX de execução de draft (2026-05-01, sessão 10):**
- Journal confirmou que os drafts v17/v18 foram escritos com sucesso em `GN_Agent_Draft` (`script_draft_write_succeeded`).
- O problema observado pelo designer era ambiguidade do botão "Executar": ele criava snapshot e mudava para estado `executing`, mas não abria o Text Editor nem validava que o bloco existia.
- `BLEND_OT_execute_draft` agora abre automaticamente o Text Editor com o draft atual antes de avançar. Se o bloco não existir, cancela com erro e não cria snapshot.
- Adicionado `BLEND_OT_open_draft` e botão "Abrir Draft" no estado `executing`, para reabrir o draft sem mudar o ciclo.
- Adicionado `BLEND_OT_run_draft`: execução manual, iniciada pelo usuário no painel, usando `bpy.ops.text.run_script()` no Text Editor com o draft atual. Após tentativa de execução, o painel vai para `awaiting_feedback`; em erro, preenche a descrição da falha.

**Diagnóstico/journal e histórico de drafts (2026-05-01, sessão 10):**
- Journals posteriores confirmaram que v18/v21 foram escritos, mas perguntas diagnósticas em REPAIRING podiam virar `focal_correction` por causa de tokens como "draft"; `_workspace_goal_mode()` agora mantém `pure_inquiry` em `diagnose_only` nesse estado.
- `handle_execution_feedback()` agora tenta gerar diagnóstico para qualquer resultado ruim (`executed_no_effect`, `executed_failed`, `executed_partial_failure`, `reverted_by_user`), relendo o draft atual antes de pedir novo detalhe ao designer.
- `write_script_draft` agora arquiva cada revisão completa em `runtime/draft_history/<session_id>/rNNNNNN_<block>.py` quando chamado pelo runtime com `session_id/project_root`. O Text Editor continua sendo o draft vivo; o arquivo é caixa-preta/histórico para comparação e reaproveitamento.
- Testes focados passaram: `test_write_script_draft_archives_full_revision_to_disk`, `test_workspace_goal_mode_keeps_repairing_draft_question_read_only`, suite `tests.test_dispatch_smoke`.

**Atualização pós-falha (2026-05-04):**
- Waves 1–3 da frente pós-falha implementadas (ver `docs/repair_conversation_loop.md` §8 para status honesto com reconciliação).
- `handle_execution_feedback()` agora prioriza `draft_history`, bloqueia reescrita automática no turno de falha e registra `STRATEGY_PROPOSED` quando há opções válidas.
- Pacote de evidência estática pós-falha identifica nós/sockets tocados, links alterados, leituras de interface, referências ausentes e conflitos semânticos com `structural_memory`.
- Testes focados de estabilização passaram (`Ran 72 tests ... OK`). A suite completa ainda pode esbarrar em testes não relacionados que dependem de tempfile/permissão no sandbox.
- **Falhas sistêmicas identificadas em sessão real (sess-20260429T143019Z-e909c754, runs de 2026-05-04):** (a) ⚠️ `STRATEGY_PROPOSED`/`REPAIRING` — espelhamento de `session_state`/`post_failure_state` pode causar dessincronização (ver "Dívida técnica atual" abaixo); (b) ⚠️ LLM falha no contrato de cabeçalhos → `_fallback_post_failure_diagnosis()` pode disparar para toda falha; (c) ✅ **RESOLVIDO** — "Caminho B" / "Opção A" agora reconhecidos via `_match_option()` em `runtime/pending_decision.py`.
