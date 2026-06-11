# Biomodel Source Mode Decision

> Branch: `codex/biomodel-source-migration`
> Status original (2026-06-03): source-mode/rebuild aceito como caminho primário.
> **Decisão revisada (2026-06-10): source-mode/rebuild rebaixado para consolidação/exportação. Caminho primário é agora árvore viva + patches incrementais via bridge.**
> Validação do ciclo incremental: `smoke_bridge.py` 5/5 passos ok.

---

## 1. Decisão Atual (2026-06-10)

O caminho primário de construção do biomodelo é:

```text
árvore viva Biomodelo  →  patches incrementais via bridge  →  verificação imediata
```

O operador nesta fase é o próprio designer usando Claude Code + socket bridge (porta 65432).
O agente embarcado no painel Blender não é prioridade nesta fase.

O source-mode (`GN_Biomodel_Source → VB_Biomodel_Generated`) permanece disponível,
mas como **modo de consolidação/exportação**, não como loop de experimentação.

Isso significa:

1. A árvore `Biomodelo` viva no Blender é o ambiente de desenvolvimento.
2. Cada mudança é um script Python pequeno, autocontido, verificável e reversível quando possível.
3. O bridge (`BlenderConnection` / canal direto `HANDLERS`) é a superfície de execução.
4. A verificação é por re-leitura imediata via bridge, não por diff/session marker.
5. O script mestre é o artefato final consolidado depois que a árvore estiver validada.
6. Snapshots são feitos apenas em marcos importantes, não a cada patch.
7. `GN_Biomodel_Source` é usado para consolidar/exportar seções prontas, não para explorar.

---

## 2. Por que a decisão mudou

A decisão original (2026-06-03) apostou que "escrever o source completo a cada turno" seria mais simples.
Na prática, produziu o problema que motivou a branch: cada turno virava um rebuild monolítico.

O que a tentativa revelou:

```text
complete source → intentional rebuild
```

é melhor como fase final de consolidação do que como loop de experimentação porque:

1. Requer que o agente mantenha o estado completo da árvore na memória.
2. Qualquer erro num turno desfaz toda a estrutura do turno anterior.
3. A verificação de "funcionou?" exige rodar o script inteiro, não um patch isolado.
4. O ciclo de feedback (errou → corrigiu → rodou → verificou) é mais lento.

O caminho incremental (patches pequenos sobre a árvore viva) resolve todos esses problemas
porque cada passo é verificável isoladamente antes de avançar.

---

## 3. Caminhos disponíveis

### Primário: patches incrementais via bridge

```text
Claude Code + BlenderConnection → execute_code (patch pequeno) → verify (re-leitura)
```

Usar quando:
- construindo ou evoluindo a árvore Biomodelo;
- adicionando nós, conectando, ajustando valores;
- explorando como implementar um comportamento novo.

Ferramentas no canal direto (sem policy gates):
- `list_tree_nodes` — inventário completo
- `find_tree_nodes` — busca por nome/label/tipo
- `get_node_context` — inspeção focal de um nó e vizinhança
- `execute_code` — execução de patch autocontido
- `capture_scene` — estado geral da cena

### Consolidação/Exportação: source-mode

```text
GN_Biomodel_Source → VB_Biomodel_Generated (rebuild quando seção está pronta)
```

Usar quando:
- uma seção da árvore já está validada e estável;
- exportando para ter um artefato reproduzível;
- gerando o script mestre do biomodelo.

Ferramentas disponíveis:
- `inspect_tree_inventory` — inventário paginado completo para extração
- `export_tree_inventory` — artefato JSON + Markdown para análise offline
- `write_biomodel_source` — escrever o source consolidado
- `validate_biomodel_source` — validar invariantes do source

### Legado: draft mutation (`GN_Agent_Draft`)

Usar apenas quando o usuário pedir explicitamente para patchear uma árvore
via o painel de chat embarcado no Blender.

---

## 4. Mapa de reúso

### Manter e usar no caminho primário

| Área | Papel |
|---|---|
| `server.py` / `BlenderBridgeServer` | bridge TCP — spine do canal direto |
| `tools/handlers.py` `HANDLERS` | handlers diretos sem gate |
| `tools/execution.py` `handle_execute_code` | primitivo de patch |
| `tools/reads.py` (`list_tree_nodes`, `find_tree_nodes`, `get_node_context`, ...) | inspeção da árvore viva |
| `blender_connection.py` `BlenderConnection` | cliente TCP do lado Claude Code |
| `smoke_bridge.py` | smoke test do ciclo mínimo |
| `snapshot_manager.py` | snapshots em marcos importantes |

### Manter para consolidação/exportação

| Área | Papel |
|---|---|
| `biomodel/source_template.py` | dado de referência — parâmetros/regiões da árvore atual |
| `biomodel/validation.py` | gate de invariantes do source consolidado |
| `tools/biomodel_source.py` | seed/read/write/validate do source completo |
| `server_dispatch` `inspect/export_tree_inventory` | extração full-tree para serialização |

### Rebaixado / fora do hot path incremental

| Área | Situação |
|---|---|
| `core/runtime.py` (AgentRuntime) | agente embarcado — fora do hot path nesta fase |
| `core/agent_loop.py`, `api_client.py` | idem |
| `runtime/router.py`, `pending_decision.py` | roteamento PT de chat |
| `handler/workspace.py`, `handler/draft_*` | goal modes, repair loops, economy_retry |
| `session/` stores | persistência de sessão de chat |
| `ui/` chat panel | interface para usuário final |

---

## 5. Invariantes (atualizadas)

1. `Biomodelo` não é mutado sem pedido explícito — permanece como referência.
2. Cada patch incremental é um script Python autocontido com print de verificação.
3. O script é executado via `execute_code` no canal direto do bridge.
4. A verificação é por re-leitura imediata (`get_node_context` / `list_tree_nodes`).
5. Snapshots `.blend` são feitos apenas em marcos, não a cada patch.
6. `GN_Biomodel_Source` é escrito apenas quando uma seção está validada e pronta para consolidar.
7. `VB_Biomodel_Generated` é descartável — pode ser recriado do source.
8. O agente embarcado (`AgentRuntime`, painel de chat) não é o canal de pilotagem nesta fase.

---

## 6. Próximo passo concreto

O ciclo mínimo está validado (`smoke_bridge.py` 5/5).

Próximo: identificar a primeira seção da árvore `Biomodelo` (126 nós) a evoluir via patches
incrementais, inspecionar essa seção via bridge e escrever o primeiro patch real de construção.
