# CURRENT_SYSTEM_AND_CLEANUP_REVIEW.md

> Revisão técnica completa do estado atual do sistema.  
> Gerado em 2026-04-08 com base na leitura direta do código-fonte.

---

## 1. Resumo Executivo

O sistema é um addon Blender que atua como copiloto de Geometry Nodes para projetos de órteses. Após o refactor, a arquitetura central funciona: o roteador de turnos, a máquina de estados, o schema de sessão v1, o loop de agente e a persistência via socket estão todos operacionais. O produto é visivelmente mais fluido.

Porém, a base de código carrega problemas reais que comprometem a experiência:

1. **Bug crítico no End Session**: a lógica "sticky" em `runtime/core.py:392` impede que `session_active` seja zerado, quebrando o gate de envio.  
2. **Baseline apagado a cada turno**: a baseline construída durante o turno é sobrescrita imediatamente após, porque `_sync_v1_session` não preserva `baseline_workspace` do V1 existente.  
3. **Prompts grandes truncados silenciosamente**: `scene.chat_input` tem limites internos do Blender; o caminho correto via Prompt Buffer existe mas não é óbvio.  
4. **Session resume confusa mas não totalmente quebrada**: reabrir o arquivo mostra o histórico mas bloqueia o envio até "New Session" ser clicado — comportamento intencional mal sinalizado.

O repositório também tem ~10–12 arquivos Python mortos dentro de `blender_addon/`, mais várias pastas raiz que poluem o projeto sem contribuir para o runtime.

---

## 2. Explicação do Sistema Atual

### O que é o software

Um addon Blender (Orthosis AI Agent v0.3.0) que embutne um agente Claude dentro do Blender. O usuário conversa num painel lateral do Viewport 3D. O agente lê e modifica árvores de Geometry Nodes autonomamente, dentro de um protocolo de aprovação explícita por turno.

### Fluxo de runtime: prompt → resposta

```
[Usuário digita no painel]
        ↓
panel.py: _send_user_message()
  - verifica session_active no V1
  - consome screenshots/attachments da fila
  - lança thread background
        ↓
panel.py: _run_chat_turn()  [thread background]
  - chama AgentRuntime.run_turn()
        ↓
agent_runtime.py: run_turn()
  1. Carrega legacy state (session_store)
  2. Carrega V1 session (v1_session_for)
  3. Classifica o turno via TurnRouter
  4. Constrói TurnContext com knowledge relevante
  5. Despacha para handler correto (dispatch_turn)
        ↓
runtime/handlers/<handler>.py
  - constructs system prompt (prompt_builder)
  - chama ctx.call_agent_loop() → agent_loop()
        ↓
runtime_agent_loop.py: agent_loop()
  - loop de tool use com Claude API
  - para cada tool_use_block:
      _execute_tool() → dispatch_tool()
        ↓
tools.py: call_blender_socket()
  - TCP para localhost:65432
  - protocolo framed: 8 dígitos de tamanho + JSON
        ↓
server.py (Blender): BlenderBridgeServer._handle_connection()
  - runtime_tool_call → Runtime.execute_tool_call()
  - executa handler Blender (capture, execute_code, etc.)
  - responde via socket
        ↓
agent_runtime.py: run_turn() (continuação)
  6. Atualiza histórico na sessão V1
  7. save_v1_session(session)
  8. _sync_v1_to_legacy() → session_store.save() → SyncedSessionStore.save()
  9. Extração de knowledge em background (maybe_extract_knowledge)
  10. Retorna response_text para panel.py
        ↓
panel.py: SESSION.add("assistant", response_text) + redraw
```

### O papel atual do MCP

O servidor TCP em `server.py` suporta o protocolo MCP via `runtime_tool_call`. Mas o caminho principal de uso é direto via addon (panel.py → AgentRuntime). O `blender_mcp_package/` na raiz do repositório é uma versão antiga/paralela sem uso no runtime atual. MCP continua funcionando como canal alternativo para chamadas externas, mas não é o caminho padrão.

---

## 3. Session / Persistência / Baseline

### Ciclo de vida da sessão

#### Start Session
```
CHAT_OT_StartSession → _start_local_runtime_session(blend_path)
  → runtime.session.begin_new_session(state)   # agent_session_active=True
  → runtime.session.save(state, blend_path)    # SyncedSessionStore.save()
    → _sync_v1_session()                        # V1 session com session_active=True
  → journal.start_session()
  → SESSION.clear()                             # Limpa UI
```

#### Active Session (durante um turno)
- O gate de envio (`_send_user_message`) verifica `v1.ui_state.session_active` lendo o arquivo V1 do disco
- Se `True`: turno prossegue
- Se `False`: "Session inactive. Click Start New Session first."
- Cada turno salva tanto o V1 (`save_v1_session`) quanto o legacy (`session_store.save`), nessa ordem

#### End Session
```
CHAT_OT_EndSession → _end_local_runtime_session(blend_path)
  → reset_session_memory, clear_pending_plan, clear_chat_history
  → set_agent_session_active(state, False)      # agent_session_active=False no legacy
  → runtime.session.save(state, blend_path)    # SyncedSessionStore.save()
    → _sync_v1_session()                        # DEVERIA setar session_active=False
  → SESSION.clear()                             # Limpa UI
```

**⚠️ BUG CONFIRMADO**: ver Seção 4, Issue 2.

#### Reopen / Resume
Ao abrir o Blender com um arquivo já usado:
1. O painel chama `_get_runtime_ui_state()` → `_load_local_runtime_session(blend_path)`
2. O legacy `.session.json` é carregado
3. `_sync_ui_messages_from_session()` detecta que há histórico e chama `SESSION.replace_messages()`
4. O histórico de chat reaparece na UI ✓
5. Mas `session_active` é lido do V1 — se o arquivo `.blend` nunca teve "New Session" nesta sessão, ou se End Session funcionou corretamente, o gate bloqueia envio
6. O usuário precisa clicar "New Session" para reativar

Este comportamento é **intencional** (não é um bug): a sessão deve ser explicitamente reiniciada. Porém, a sinalização é confusa — o histórico aparece mas o envio falha silenciosamente.

### Como persiste o estado hoje

**Dois stores em paralelo:**

| Store | Arquivo | Schema | Diretório |
|---|---|---|---|
| Legacy (SessionStore) | `<hash>.session.json` | flat dict, v0.1 | `runtime/sessions/` |
| V1 (SessionV1Store) | `<hash>.session.json` | 7 blocos tipados | `runtime/sessions_v1/` |

O `SyncedSessionStore` envolve o legacy: toda save no legacy dispara automaticamente um `_sync_v1_session()` que reescreve o V1.

**Autoridade atual:** O V1 é autoridade para `session_active` e `execution_state.phase`. O legacy é autoridade para todo o resto (histórico legível pela UI, `last_target_tree`, `recent_actions`, etc.). Esta divisão é transitória e é fonte de bugs.

### Como funciona a baseline hoje

A `BaselineWorkspace` no V1 session contém:
- `structural_summary`: snapshot da estrutura GN
- `subgraph_index`: índice de nós por árvore
- `known_parameters`: parâmetros conhecidos
- `stale`: flag de validade

A baseline é **marcada como stale** por padrão em sessões novas. É construída pelo `BaselineBuilder` quando o handler `baseline_refresh` é disparado, ou atualizada em `_apply_tool_result_to_v1_session` após chamadas de `get_tree_structure` / `analyze_gn_state`.

**⚠️ BUG CONFIRMADO**: ver Seção 4, Issue 4.

### Como funciona o approval hoje

Não há mais tokens de aprovação. O mecanismo é puramente baseado em fase:

```
idle → (mutation_request handler) → awaiting_confirmation
  → "sim" → executing → (ferramenta roda) → idle
  → "não" → idle
  → qualquer outra mensagem → cancela pendente + reclassifica
```

A fase vive em `session.execution_state.phase` (V1 schema). A guard em `_execute_tool` (agent_runtime.py) bloqueia qualquer mutation tool se `phase != "executing"`.

---

## 4. Diagnóstico dos Problemas Observados

### Issue 1: Session resume/reopen parece não confiável

**Status: parcialmente confirmado — comportamento intencional mal sinalizado**

**Causa raiz:**  
Ao reabrir o Blender, o histórico de chat reaparece na UI (via `_sync_ui_messages_from_session`), mas o gate de envio lê `v1.ui_state.session_active` do arquivo V1. Se a sessão anterior foi encerrada corretamente, este valor é `False` e o envio é bloqueado.

O confundimento vem de: o usuário vê o histórico, tenta enviar, recebe "Session inactive" — sem contexto claro de por que o histórico está visível mas não pode enviar.

**O que deveria acontecer:** A UI deveria mostrar uma mensagem mais clara ao exibir histórico de sessão encerrada: "Sessão anterior — clique em New Session para continuar."

**O que NÃO está quebrado:** O carregamento do histórico funciona, o V1 é lido corretamente, o gate funciona como projetado.

---

### Issue 2: End Session não funciona como gate de envio ⚠️ BUG CRÍTICO

**Status: bug confirmado no código**

**Localização:** `blender_addon/runtime/core.py`, linhas 392–393

**Código problemático:**
```python
if existing.ui_state.session_active and not session.ui_state.session_active:
    session.ui_state.session_active = existing.ui_state.session_active
```

**O que acontece:**
1. End Session seta `agent_session_active=False` no legacy
2. `SyncedSessionStore.save()` → `_sync_v1_session()`
3. `migrate_legacy_state` cria sessão nova com `session_active=False` ✓
4. PORÉM: o V1 existente no disco ainda tem `session_active=True` (da sessão ativa anterior)
5. A lógica "sticky" detecta `existing=True` e `novo=False` → **força `session_active=True` de volta**
6. V1 é salvo com `session_active=True`
7. O gate de envio lê V1 → `session_active=True` → **permite envio mesmo após End Session**

**Intenção original da lógica:** Evitar que um save intermediário (ex: durante tool call) apague acidentalmente um `session_active=True` válido. A ideia fazia sentido para o caso onde a migração legacy não tinha certeza se a sessão era ativa ou não. Mas ela também impede que End Session funcione.

**Fix necessário:** A lógica sticky deve ser aplicada apenas quando o contexto é um save de ferramenta/operação, não quando é um save explícito de ciclo de vida (begin/end session). A forma mais simples: adicionar um parâmetro `lifecycle_event: bool = False` e pular a lógica sticky quando `lifecycle_event=True`.

---

### Issue 3: Prompts muito longos não passam corretamente

**Status: confirmado como limitação de implementação + comportamento não documentado**

**Causa 1 — `scene.chat_input` (principal):**  
O operador `CHAT_OT_SendMessage` lê `context.scene.chat_input` (um `bpy.props.StringProperty`). O Blender impõe um limite interno a `StringProperty` que varia com a versão, mas na prática prompts acima de ~4.000 caracteres podem ser silenciosamente truncados ou causar undefined behavior no PropertyGroup.

**Causa 2 — `_recv_all` no server.py (secundária, afeta respostas de ferramenta):**  
O método `_recv_all` (linhas 229–265) tem uma detecção de protocolo frágil:
```python
if len(first) >= 8 and first[:8].isdigit():
    expected = int(first[:8])  # protocolo framed
```
Se o primeiro chunk recebido tem menos de 8 bytes (possível com payloads grandes fragmentados em TCP), ou se os primeiros 8 bytes do JSON de resposta não parecem um número, o protocolo fallback (timeout de 1s) é usado. Para respostas grandes de ferramentas (ex: `get_tree_structure` de uma árvore complexa), isso pode causar timeout premature ou dados parciais.

**Caminho correto para prompts longos:**  
`CHAT_OT_OpenPromptBuffer` → edita no Text Editor → `CHAT_OT_SendPromptBuffer`. Esse caminho lê de um `bpy.types.Text` (sem limite). Ele existe, está implementado, mas não é visualmente prominente na UI.

**O que deve ser feito:** Tornar o Prompt Buffer o caminho padrão para prompts multi-linha; ou aumentar o prominence dos botões Open/Send Buffer na UI.

---

### Issue 4: Baseline persistence não funciona como esperado ⚠️ BUG CONFIRMADO

**Status: bug confirmado no código**

**Localização:** `blender_addon/runtime/core.py`, método `_sync_v1_session()`, e `agent_runtime.py`, método `run_turn()`.

**O que acontece em cada turno:**
```
run_turn() linha 231: save_v1_session(session)
  → runtime/sessions_v1/<hash>.session.json salvo com baseline atualizada ✓

run_turn() linha 234: _sync_v1_to_legacy(session, legacy_state, blend_path)
  → session_store.save(legacy_state, blend_path)
  → SyncedSessionStore.save()
  → _sync_v1_session(legacy_state)
    → migrate_legacy_state(legacy_state)  ← CRIA NOVA sessão do zero
      → BaselineWorkspace nova, construída apenas dos campos legacy
        (last_gn_summary, last_scene_summary, structural_index)
    → Copia do existing: focus.*, lifecycle.*, ui_state.advanced_open
    → NÃO copia existing.baseline_workspace  ← PROBLEMA
    → v1_store.save(session_nova)  ← SOBRESCREVE o arquivo salvo em linha 231
```

**Resultado:** A baseline construída com `BaselineBuilder.rebuild_from_summary()` durante o turno é **perdida imediatamente após o turno terminar**. Na próxima chamada a `v1_session_for()`, a baseline lida terá apenas o que a migração legacy consegue reconstruir (geralmente muito mais pobre).

**Fix necessário:** Em `_sync_v1_session`, adicionar:
```python
if existing is not None:
    # Preserve rich baseline from V1 unless explicitly stale.
    if not session.baseline_workspace.is_built() and existing.baseline_workspace.is_built():
        session.baseline_workspace = existing.baseline_workspace
```

Esta é uma linha de fix, mas com consequências que precisam ser verificadas (ex: se a baseline preservada é de um turn muito antigo). A abordagem mais robusta é rever o modelo de autoridade — o V1 deveria ser salvo DEPOIS do sync legacy, não antes.

---

## 5. Mapa de Arquivos: Live vs Transitional vs Legacy

### 5.1 Arquivos LIVE (núcleo do runtime atual)

```
blender_addon/
├── __init__.py                    ✅ LIVE — registro do addon
├── agent_runtime.py               ✅ LIVE — orquestrador de turno
├── capture.py                     ✅ LIVE — snapshots de cena/GN
├── knowledge_updater.py           ✅ LIVE — aprendizado automático
├── operation_journal.py           ✅ LIVE — audit trail JSONL
├── server.py                      ✅ LIVE — socket bridge Blender
├── tools.py                       ✅ LIVE — registry + cliente socket
├── handlers.py                    ✅ LIVE — handlers diretos (captura, execute_code)
│
├── runtime/                       ✅ LIVE — roteador + máquina de estados
│   ├── __init__.py
│   ├── core.py
│   ├── router.py
│   ├── state_machine.py
│   ├── prompt_builder.py
│   └── handlers/                  ✅ LIVE
│       ├── __init__.py
│       ├── greeting.py
│       ├── clarification.py
│       ├── diagnosis.py
│       ├── baseline_refresh.py
│       ├── proposal.py
│       ├── mutation_request.py
│       ├── mutation_confirmation.py
│       ├── mutation_denial.py
│       └── post_failure_recovery.py
│
├── session/                       ✅ LIVE — schema V1 estruturado
│   ├── __init__.py
│   ├── schema.py
│   ├── store.py
│   ├── baseline.py
│   └── history.py
│
├── execution/                     ✅ LIVE — dispatcher consolidado
│   ├── __init__.py
│   └── dispatcher.py
│
├── knowledge/                     ✅ LIVE — retriever de knowledge
│   ├── __init__.py
│   ├── corpus.py
│   └── retriever.py
│
└── ui/                            ✅ LIVE — painel Blender
    ├── __init__.py
    ├── panel.py
    ├── chat_session.py
    ├── screenshot.py
    ├── advanced.py
    └── _helpers.py
```

### 5.2 Arquivos TRANSITIONAL (ainda necessários, sendo substituídos)

Estes arquivos ainda são importados pelo runtime ativo. Não devem ser removidos ainda, mas são candidatos à remoção em uma fase futura quando as dependências forem eliminadas.

```
blender_addon/
├── session_store.py               🟡 TRANSITIONAL
│   Importado por: runtime/core.py
│   Motivo: SyncedSessionStore ainda envolve SessionStore
│   Substituto futuro: V1 SessionV1Store completo

├── runtime_dispatch.py            🟡 TRANSITIONAL
│   Importado por: runtime/core.py (Runtime.dispatcher)
│   Motivo: ainda é o dispatcher principal de ferramentas Blender
│   Substituto futuro: execution/dispatcher.py (em andamento)

├── safety_policy.py               🟡 TRANSITIONAL
│   Importado por: runtime/core.py (evaluate_tool_call)
│   Motivo: still gates tool calls via policy
│   CLAUDE.md diz "Não recriar safety_policy.py" mas ela existe e é usada

├── skill_router.py                🟡 TRANSITIONAL
│   Importado por: runtime_dispatch.py (SkillRouter)
│   Motivo: routing de ferramentas via dispatch
│   CLAUDE.md diz "Não recriar skill_router.py" mas ela existe e é usada

├── runtime_planning.py            🟡 TRANSITIONAL
│   Importado por: agent_runtime.py (FOCAL_READ_TOOLS, MUTATION_TOOLS, helpers)
│   Motivo: constantes e helpers ainda usados no core

├── runtime_agent_loop.py          🟡 TRANSITIONAL
│   Importado por: agent_runtime.py (agent_loop, send_screenshot_turn)
│   Motivo: loop de tool-use com Claude ainda vive aqui

├── runtime_api_client.py          🟡 TRANSITIONAL
│   Importado por: agent_runtime.py (request_with_retry, extract_text, etc.)
│   Motivo: cliente API com retry logic

├── runtime_state_sync.py          🟡 TRANSITIONAL
│   Importado por: agent_runtime.py (update_operational_state_from_tool)
│   Motivo: sincronização de estado pós-ferramenta

└── simulator_mapper.py            🟡 TRANSITIONAL
    Importado por: runtime_dispatch.py (lazy import para apply_simulator_payload)
    Motivo: mapeamento de payload de simulador para ops GN
```

### 5.3 Arquivos MORTOS (não importados por nenhum caminho ativo)

```
blender_addon/
├── runtime_governance.py          ❌ MORTO
│   Comentário no código: "runtime_governance imports removed in Phase 4"
│   Nenhum import encontrado. Tombstone explícito.

├── runtime_execution.py           ❌ MORTO
│   Substituído por execution/dispatcher.py
│   Nenhum import encontrado. Tombstone explícito no dispatcher.py.

├── runtime_context.py             ❌ MORTO
│   Comentário no arquivo: "No live code paths import this module"
│   Tombstone explícito.

├── runtime_turn.py                ❌ MORTO
│   Substituído por runtime/ (TurnRouter + handlers)
│   Referenciado apenas em comentários de docstring no agent_runtime.py.

├── context_knowledge.py           ❌ MORTO
│   Substituído por knowledge/ subpackage
│   context_prompt.py também refere a ele como "tombstoned"

├── context_prompt.py              ❌ MORTO
│   Substituído por runtime/prompt_builder.py
│   Nenhum import encontrado.

├── context_skills.py              ❌ MORTO
│   Substituído por knowledge/ subpackage
│   Nenhum import encontrado.

├── execution_dispatch.py          ❌ MORTO
│   Substituído por execution/dispatcher.py
│   O dispatcher.py tem comentário explícito: "absorbs logic from now-deprecated execution_dispatch.py"

├── execution_postprocess.py       ❌ MORTO
│   Comentário no arquivo: "no live code paths import this module"
│   Tombstone explícito.

└── execution_prechecks.py         ❌ MORTO (provavelmente)
    Verificar: nenhum import encontrado na análise.
    Parte do trio execution_dispatch/postprocess/prechecks, todos superseded.
```

### 5.4 Arquivos na raiz do repositório

```
Raiz/
├── REFATOR_PLAN.md                ✅ LIVE — referência de decisões de arquitetura
├── CLAUDE.md                      🟡 DESATUALIZADO — descreve estado anterior; precisa ser atualizado
├── PHASE1_NOTES.md .. PHASE9_NOTES.md  🟡 TRANSITIONAL — histórico de implementação
├── QUESTIONS.md                   🟡 TRANSITIONAL — perguntas abertas de design
│
├── blender_connection.py          🟡 INCERTO — conector externo; não faz parte do addon
│   Origem e uso atuais não confirmados.
│
├── mcp_policy.py                  🟡 INCERTO — política MCP; não importado pelo addon
│   Pode ser ferramenta de dev/teste, não runtime.
│
├── server.py (RAIZ)               ⚠️ INCERTO — DIFERENTE de blender_addon/server.py
│   Arquivo na raiz do projeto, não dentro do addon.
│   Precisa ser inspecionado: pode ser um servidor MCP externo ou artifact legado.
│
├── arquitetura_agentes.md         ❌ LEGACY — arquitetura multi-agente não implementada
├── ecossistema_limbse.md          ❌ LEGACY — design doc de ecossistema mais amplo
├── prompt_claude_code.md          ❌ LEGACY — prompts de desenvolvimento, não runtime
├── tmp_session_slice.txt          ❌ DELETAR — arquivo temporário explícito
├── blender_addon.zip              🟡 BUILD ARTIFACT — manter apenas se necessário para deploy
│
├── knowledge/                     ✅ LIVE — corpus de knowledge usado pelo runtime
├── runtime/                       ✅ LIVE — journal e sessions em disco
│
├── skills/                        🟡 INCERTO
│   Definições elaboradas de skills (gn_scene_state_interpreter, scene_context_inspector)
│   Não encontradas como imports no runtime atual. Podem ser usadas como referência
│   pelo modelo ou podem ser vestigiais.
│
├── contracts/                     🟡 INCERTO — schemas JSON não validados em código
│   journal_event.schema.json, etc. Úteis como documentação, não runtime.
│
├── docs/                          🟡 REFERÊNCIA — docs de arquitetura e design
│
├── blender_mcp_package/           ❌ MORTO — versão antiga do MCP package
│   Duplica conhecimento do knowledge/. Marcado para deleção no REFATOR_PLAN.
│
├── reference/                     ❌ MORTO — scripts de referência antigos
│   exec.py, generator_base.py, initialize_plan.py, investigator.py
│
└── snapshots/                     ❌ MORTO — snapshots de código antigos (gitignore)
    current_20260401_213329/ e restore_from_...
```

---

## 6. Conteúdo Proposto para `legacy/`

Mover para `legacy/` (preservar caso precise de referência):

```
legacy/
├── blender_addon_flat_modules/    # módulos mortos do blender_addon/
│   ├── runtime_governance.py
│   ├── runtime_execution.py
│   ├── runtime_context.py
│   ├── runtime_turn.py
│   ├── context_knowledge.py
│   ├── context_prompt.py
│   ├── context_skills.py
│   ├── execution_dispatch.py
│   ├── execution_postprocess.py
│   └── execution_prechecks.py
│
├── blender_mcp_package/          # versão antiga do MCP (raiz)
├── reference/                    # scripts de referência antigos
├── docs/                         # docs de arquitetura (podem virar legacy ou archive)
├── arquitetura_agentes.md
├── ecossistema_limbse.md
└── prompt_claude_code.md
```

---

## 7. Arquivos / Pastas que Devem Ser Deletados (não arquivados)

Estes não têm valor de referência e poluem o repositório:

```
tmp_session_slice.txt              # arquivo temporário — deletar
snapshots/                         # snapshots de código — deletar
blender_addon/__pycache__/        # bytecode — já no .gitignore mas verificar
```

O arquivo `blender_addon.zip` pode ser deletado se o deploy é feito de outra forma (ou movido para um diretório `dist/`).

---

## 8. Próximas Ações Recomendadas (em ordem)

### Prioridade 1 — Bugs que afetam o produto hoje

**8.1 Fix: End Session não desativa o gate de envio**  
Arquivo: `blender_addon/runtime/core.py`, linha 392  
Adicionar um parâmetro `is_lifecycle_save: bool = False` para `_sync_v1_session` e pular a lógica sticky quando `True`. Chamar com `is_lifecycle_save=True` de `begin_new_session` e `end_session` no `SyncedSessionStore`.  
Estimativa: 15–20 linhas.

**8.2 Fix: Baseline sobrescrita a cada turno**  
Arquivo: `blender_addon/runtime/core.py`, método `_sync_v1_session()`  
Adicionar preservação de `baseline_workspace` do existing quando a nova migração produz uma baseline vazia:
```python
if existing is not None and not session.baseline_workspace.is_built():
    if existing.baseline_workspace.is_built():
        session.baseline_workspace = existing.baseline_workspace
```
Verificar também a ordem de operações em `agent_runtime.run_turn()`: `save_v1_session` antes, `_sync_v1_to_legacy` depois (atual) está correta, mas o problema é que o sync sobrescreve. A lógica acima resolve isso de forma conservadora.

### Prioridade 2 — Experiência do usuário

**8.3 Melhoria: Sinalização de sessão encerrada ao abrir arquivo**  
Em `_get_runtime_ui_state()`, quando histórico existe mas `session_active=False`, adicionar um `session_resumed_notice` claro: "Sessão anterior disponível. Clique em New Session para continuar."

**8.4 Melhoria: Prompt Buffer mais visível para prompts longos**  
No painel, adicionar nota de aviso quando `scene.chat_input` exceder ~1000 chars sugerindo usar o Prompt Buffer.

### Prioridade 3 — Limpeza de repositório

**8.5 Mover arquivos mortos para `legacy/`**  
Mover os 10 módulos Python mortos de `blender_addon/` para `legacy/blender_addon_flat_modules/`.  
Verificar que nenhum `__init__.py` ou import ativo os referencia antes de mover.

**8.6 Deletar artefatos**  
```
rm tmp_session_slice.txt
rm -rf snapshots/
```

**8.7 Mover pastas raiz para `legacy/`**  
```
blender_mcp_package/  → legacy/
reference/            → legacy/
arquitetura_agentes.md, ecossistema_limbse.md, prompt_claude_code.md → legacy/
```

**8.8 Classificar arquivos incertos**  
Inspecionar antes de mover:
- `server.py` (raiz) — é um servidor MCP externo? Se sim, documentar ou mover para `tools/mcp_server.py`
- `blender_connection.py` — para que serve hoje? Se for debug/dev, mover para `tools/`
- `mcp_policy.py` — ainda relevante? Se não, deletar ou arquivar

**8.9 Atualizar CLAUDE.md**  
O atual está desatualizado. Descreve `make_plan` obrigatório antes de `execute_code` (que era o regime anterior), não menciona o TurnRouter nem a máquina de estados. Reescrever para refletir o estado pós-refactor.

### Prioridade 4 — Dívida técnica de médio prazo

**8.10 Eliminar a dualidade Legacy/V1**  
O objetivo final é ter apenas o V1 como fonte de autoridade. Isso requer:
- Migrar `session_store.py` (legacy) para wrapper thin sobre V1
- Eliminar `SyncedSessionStore` e `_sync_v1_session`
- Fazer `agent_runtime.run_turn()` operar puramente sobre o V1

**8.11 Consolidar módulos transitional**  
A longo prazo, os 8 módulos transitional (runtime_dispatch, safety_policy, runtime_planning, etc.) devem ser absorvidos pelos subpackages correspondentes (`execution/`, `runtime/`, etc.) e removidos.

---

*Documento gerado por inspeção direta do código-fonte em 2026-04-08.*  
*Fonte de verdade: arquivos em `blender_addon/` conforme lidos nesta sessão.*
