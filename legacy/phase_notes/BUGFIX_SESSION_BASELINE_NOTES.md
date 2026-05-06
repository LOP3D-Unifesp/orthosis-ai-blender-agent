# BUGFIX_SESSION_BASELINE_NOTES.md

> Priority 1 fixes from CURRENT_SYSTEM_AND_CLEANUP_REVIEW.md.  
> Implementado em 2026-04-08. Suite: 334 tests, 0 falhas, 2 skips pré-existentes.

---

## Escopo dos fixes

Um único arquivo modificado: `blender_addon/runtime/core.py`  
Um arquivo de testes adicionado: `tests/test_bugfix_session_baseline.py`  
Nenhum refactor adicional. Nenhum arquivo movido.

---

## §1 — Bug 1: End Session não bloqueava o gate de envio

### Causa raiz confirmada

Arquivo: `blender_addon/runtime/core.py`, método `_sync_v1_session()`.

O bloco de "sticky preservation" (originalmente nas linhas 392–393) executava de forma incondicional:

```python
# ANTES (código com bug):
if existing.ui_state.session_active and not session.ui_state.session_active:
    session.ui_state.session_active = existing.ui_state.session_active
```

**Cadeia de eventos que produzia o bug:**

1. `_end_local_runtime_session()` (panel.py) chamava `set_agent_session_active(state, False)` → `agent_session_active=False` no dict legacy
2. `runtime.session_store.save(state, blend_path)` → `SyncedSessionStore.save()` → `_sync_v1_session()`
3. Dentro de `_sync_v1_session()`:
   - `migrate_legacy_state(legacy_state)` lia `agent_session_active=False` e produzia corretamente `session_active=False`
   - Mas o V1 existente em disco ainda tinha `session_active=True` (da sessão ativa anterior)
   - A sticky logic detectava `existing=True` e `novo=False` → **sobrescrevia de volta para True**
4. V1 era salvo com `session_active=True` mesmo após End Session
5. O gate em `_send_user_message()` lia o V1 → `session_active=True` → envio ainda liberado

**Intenção original da sticky logic:** proteger contra um save intermediário (ex: resultado de ferramenta) que chegasse com um legacy state que não tivesse `agent_session_active` setado, zerando acidentalmente uma sessão ativa válida.

### Fix aplicado

```python
# DEPOIS (código corrigido):
legacy_explicitly_inactive = not bool(
    legacy_state.get("agent_session_active", True)
)
if (
    existing.ui_state.session_active
    and not session.ui_state.session_active
    and not legacy_explicitly_inactive
):
    session.ui_state.session_active = existing.ui_state.session_active
```

**Lógica:** a sticky só roda quando o legacy dict **não afirma explicitamente** que a sessão está inativa. Se `agent_session_active=False` está presente no dict (como é o caso após `set_agent_session_active(state, False)`), a migração é autoritativa e não deve ser sobrescrita.

**Por que é seguro:**
- `agent_session_active` é sempre inicializado em `_default_state()`, logo nunca está ausente em estados legítimos
- `begin_new_session()` seta `True` → `legacy_explicitly_inactive=False` → sticky pode proteger se necessário
- `set_agent_session_active(False)` seta `False` → `legacy_explicitly_inactive=True` → sticky é pulado ✓
- Saves de ferramenta com sessão ativa: `agent_session_active=True` → `legacy_explicitly_inactive=False` → comportamento idêntico ao anterior ✓

### Comportamentos preservados

- A sticky ainda protege quando o campo está ausente (estados muito antigos sem o campo)
- A sticky ainda protege quando `agent_session_active=True` (sessão ativa, save de ferramenta)
- Baseline de sessão anterior não sangra para nova sessão (IDs diferentes → bloco inteiro não executa)

---

## §2 — Bug 2: Baseline destruída a cada turno

### Causa raiz confirmada

Arquivo: `blender_addon/runtime/core.py`, método `_sync_v1_session()`.

**Cadeia de eventos que produzia o bug:**

Em `agent_runtime.run_turn()`:
```
linha 231: save_v1_session(session)           # salva V1 com baseline construída ✓
linha 234: _sync_v1_to_legacy(session, ...)   # espelha V1 → legacy
  → session_store.save(legacy_state, ...)
  → SyncedSessionStore.save()
  → _sync_v1_session(legacy_state)            # BUG: sobrescreve o V1 recém-salvo
      → migrate_legacy_state(legacy_state)    # produz nova Session do zero
          → BaselineWorkspace nova:
              tree_signature = ""             # sempre vazio (is_built() = False)
              built_at = ""                   # sempre vazio
              structural_summary = {thin}     # só o que legacy tem
      → NÃO copia existing.baseline_workspace
      → v1_store.save(session_nova)           # sobrescreve o arquivo salvo em linha 231
```

`migrate_legacy_state()` **nunca** produz uma baseline com `tree_signature` ou `built_at` preenchidos. Portanto `is_built()` sempre retorna `False` após migração. A baseline rica construída pelo `BaselineBuilder.rebuild_from_summary()` (que preenche `tree_signature`, `built_at`, `subgraph_index`, `known_parameters`) era perdida a cada turno, neste segundo save.

### Fix aplicado

```python
# DEPOIS (código corrigido — dentro do bloco session_id match):
if existing.baseline_workspace.is_built():
    session.baseline_workspace = existing.baseline_workspace
```

**Lógica:** `migrate_legacy_state()` nunca produz uma baseline built. Se o V1 existente tem uma baseline built, ela representa dados estruturais mais ricos do que qualquer coisa que a migração pode reconstruir. A preservamos como ponto de partida.

`_apply_tool_result_to_v1_session()` (chamado logo depois) continua podendo:
- Atualizar a baseline via `BaselineBuilder.rebuild_from_summary()` (para `get_tree_structure`)
- Marcar stale via `session.mark_baseline_stale()` (para mutações e `get_changes_since_last_turn`)

Ou seja: a baseline preservada ainda está sujeita às transições normais de staleness do turno atual.

**Por que só dentro do bloco session_id match:**  
A preservação só ocorre quando o V1 existente pertence à **mesma sessão**. Se o `session_id` mudou (nova sessão via `begin_new_session`), o bloco inteiro não executa, e a nova sessão começa com baseline vazia — comportamento correto.

**Baselines stale também são preservadas:**  
Uma baseline `stale=True, is_built()=True` ainda contém dados estruturais valiosos (subgraph_index, known_parameters). Preservar mesmo stale é preferível a descartar. O flag stale já sinaliza ao handler que um refresh é necessário antes de usar para propostas de mutação.

### Comportamentos preservados

- Tool result de `get_tree_structure` ainda atualiza a baseline normalmente (via `_apply_tool_result_to_v1_session`)
- Mutação ainda marca baseline como stale (via `session.mark_baseline_stale()`)
- `get_changes_since_last_turn` com mudanças ainda marca stale
- Nova sessão (session_id diferente) começa com baseline vazia
- Uma baseline nunca-construída não ganha dados inventados

---

## §3 — Testes adicionados

Arquivo: `tests/test_bugfix_session_baseline.py`

| Classe | Teste | Cobre |
|---|---|---|
| `TestEndSessionGateFix` | `test_end_session_sets_session_inactive_in_v1` | Bug 1 core — End Session → V1 False |
| `TestEndSessionGateFix` | `test_start_new_session_re_enables_after_end` | Start New Session → V1 True |
| `TestEndSessionGateFix` | `test_sticky_still_applies_when_legacy_field_absent` | Caso original da sticky ainda funciona |
| `TestEndSessionGateFix` | `test_end_session_survives_intermediate_tool_sync` | False sobrevive a sync adicional pós-End |
| `TestEndSessionGateFix` | `test_no_session_active_bleed_across_session_ids` | Sem bleed cross-session |
| `TestBaselinePreservationFix` | `test_built_baseline_survives_post_turn_sync` | Bug 2 core — baseline sobrevive ao sync |
| `TestBaselinePreservationFix` | `test_rich_v1_baseline_preferred_over_migrated_baseline` | V1 rico > migração pobre |
| `TestBaselinePreservationFix` | `test_stale_built_baseline_preserved_over_empty` | Stale ainda é preservada |
| `TestBaselinePreservationFix` | `test_no_baseline_preserved_when_v1_never_built` | Nenhuma invenção de baseline vazia |
| `TestBaselinePreservationFix` | `test_tool_result_baseline_not_blocked_by_preservation` | Tool result ainda atualiza baseline |
| `TestBaselinePreservationFix` | `test_baseline_not_carried_to_new_session` | Nova sessão sem baseline herdada |
| `TestBothFixesIntegration` | `test_full_cycle_session_and_baseline` | Ciclo completo: start → build → end → start |

Resultado: **12/12 passing**, **334 total** (suite completo), **0 regressões**.

---

## §4 — Edge cases restantes

### Bug 1
- **`set_modes` via socket MCP com `agent_session_active`**: o caminho `runtime_set_modes` em `core.py` chama `set_agent_session_active()` no legacy e depois persiste. O fluxo passa por `_sync_v1_session()` indiretamente. O fix funciona para este path também porque o valor de `agent_session_active` no dict é o mesmo.
- **Blender crash mid-session**: o V1 fica em disco com `session_active=True`. Ao reabrir, o gate libera envio (o usuário pode continuar). Comportamento intencional — não é bug.
- **Dois processos Blender com o mesmo .blend**: race condition de escrita no .session.json. Fora do escopo deste fix.

### Bug 2
- **Baseline construída DEPOIS do `save_v1_session` e ANTES do `_sync_v1_to_legacy`**: este cenário não existe no runtime atual (baseline é construída durante o turn, antes de qualquer save). Se o fluxo mudar no futuro, verificar se ainda está correto.
- **Baseline construída via `_apply_tool_result_to_v1_session` durante o sync**: este é o caminho `get_tree_structure` → sync com tool result. Funciona corretamente: a baseline é construída/atualizada pelo `_apply_tool_result_to_v1_session` após a preservação, então o resultado é a baseline mais recente do tool result.
- **Focus muda durante o sync**: `_apply_runtime_state_to_v1_session` chama `session.update_focus()` que, se o focus realmente mudar, chama `baseline_workspace.mark_stale()`. A baseline preservada ficará stale se o foco mudou. Comportamento correto: a baseline era de outro contexto.

---

## §5 — Resumo do que mudou

```
blender_addon/runtime/core.py
  _sync_v1_session():
    + legacy_explicitly_inactive check (Bug 1)
    + baseline preservation for same-session syncs (Bug 2)
    Total: +23 linhas (comentários incluídos), 0 linhas removidas

tests/test_bugfix_session_baseline.py  [novo]
  12 testes cobrindo os dois fixes e edge cases
```

Nenhuma interface pública foi alterada. Nenhum import foi adicionado. Nenhum arquivo foi movido ou deletado.
