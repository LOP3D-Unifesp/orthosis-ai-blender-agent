# LEGADO — Agente Embarcado

Arquivado em 2026-06-11 quando o fluxo principal mudou para patches incrementais
via socket bridge (Claude Code → porta 65432).

O agente embarcado (painel Blender → AgentRuntime → draft mutation) ainda funciona
como caminho alternativo mas não é prioridade nesta fase.

---

## O que está aqui

| Diretório | Conteúdo |
|---|---|
| `addon/core/` | AgentRuntime, agent_loop, api_client, tool_policy |
| `addon/handler/` | workspace, draft_*, feedback* |
| `addon/runtime/` | Runtime Blender-side, router PT, pending_decision, session |
| `addon/session/` | stores V1, ChatHistory, schema |
| `addon/tools/` | draft.py, client.py, schemas.py, edits.py, query.py, server_dispatch.py, structural.py, tree_analysis.py |
| `addon/ui/` | painel de chat, ciclo de execução, operadores |
| `addon/` (raiz) | fast_path.py, model_policy.py, text_utils.py, operation_journal.py, safety_policy.py, runtime_planning.py |
| `docs/` | draft_flow_audit, repair_conversation_loop, state_inventory, SLIM_REFACTOR_PLAN, refactor_handoff/ |
| `tests/` | testes do agente embarcado |

## Contexto

O slim refactor (2026-05-06 a 2026-05-31) organizou o agente embarcado nos módulos acima.
Ver `legacy/docs/SLIM_REFACTOR_PLAN.md` para o histórico das fases 1–5.

O motivo do arquivamento está em `docs/BIOMODEL_SOURCE_MODE_DECISION.md`:
o rebuild monolítico via agente era lento para exploração; patches incrementais
diretos via bridge são mais rápidos e verificáveis.
