# CLAUDE.md — blend_IA_ort

> **Fluxo ativo:** Claude Code + socket bridge + patches incrementais sobre a árvore viva.
> Este arquivo é atualizado após cada sessão de trabalho para registrar fase, o que foi feito e próximos passos.

---

## O que é este projeto

Ferramentas Python para construir e evoluir a árvore Geometry Nodes `Biomodelo` dentro do Blender,
usando Claude Code como operador externo via socket bridge (porta 65432).

O objetivo final é um script Python mestre executável no Blender que gera o biomodelo parametrizável
de membro superior a partir de medidas clínicas.

**Dois artefatos:**

| Artefato | Status |
|---|---|
| `Biomodelo` (árvore viva) | ambiente de desenvolvimento — patcheada incrementalmente |
| `GN_Biomodel_Source` (Text Editor) | script mestre de consolidação — escrito apenas quando seções estão prontas |

---

## Fluxo de trabalho

```text
Claude Code
  └── blender_connection.py  (BlenderConnection)
        └── TCP localhost:65432
              └── blender_addon/server.py  (BlenderBridgeServer)
                    └── tools/handlers.py  (HANDLERS)
                          ├── execute_code        — patch incremental
                          ├── list_tree_nodes     — inventário completo
                          ├── find_tree_nodes     — busca por nome/label/tipo
                          ├── get_node_context    — inspeção focal de nó + vizinhança
                          └── capture_scene       — ping + estado geral
```

**O operador desta fase é Claude Code.**
O painel de chat embarcado no Blender está arquivado em `legacy/` — não é prioridade.

---

## Ferramentas disponíveis via bridge (canal direto)

| Ferramenta | Uso |
|---|---|
| `capture_scene()` | ping + estado geral da cena (health check) |
| `list_tree_nodes(tree_name)` | inventário completo de nós |
| `find_tree_nodes(tree_name, name_contains=...)` | busca por nome/label/tipo |
| `get_node_context(tree_name, node_name, radius=1)` | inspeção focal: nó + vizinhança |
| `get_selected_nodes_context(tree_name)` | contexto dos nós selecionados |
| `get_active_frame_context(tree_name, frame_name)` | contexto de um frame |
| `execute_code(code)` | executa script Python no Blender |
| `capture_node_trees()` | snapshot de todas as árvores GN |
| `read_biomodel_source(block_name)` | lê o source canônico do Text Editor |
| `write_biomodel_source(block_name, code, description)` | escreve source validado |
| `validate_biomodel_source(code)` | valida invariantes sem executar |
| `seed_biomodel_source()` | semente o template fase-1 no Text Editor |

**Ponto de entrada Python:** `BlenderConnection` em `blender_connection.py`.

```python
from blender_connection import BlenderConnection
conn = BlenderConnection()
conn.capture_scene()                                        # ping
conn.list_tree_nodes("Biomodelo")                          # inventário
conn.get_node_context("Biomodelo", "Antebraco_Scale")      # inspeção focal
conn.execute_code("import bpy; print('ok')")               # patch
```

**Smoke test:** `python smoke_bridge.py --tree Biomodelo`

---

## Invariantes do fluxo incremental

1. `Biomodelo` é a árvore de desenvolvimento — patcheada incrementalmente, não substituída.
2. Cada patch = 1 script Python autocontido com `print()` de verificação.
3. O patch é executado via `execute_code` no canal direto.
4. A verificação é por re-leitura imediata: `get_node_context` / `list_tree_nodes` após o patch.
5. Snapshots `.blend` apenas em marcos importantes (não a cada patch).
6. `GN_Biomodel_Source` é escrito **somente** quando uma seção está visualmente validada.
7. `VB_Biomodel_Generated` é descartável — gerado pelo source, pode ser recriado.
8. Para sockets de interface Group Input/Output em scripts Python: usar `socket.identifier`.
9. Para sockets internos de nó: usar `socket.name`.

---

## Estado atual da parametrização

> **Atualizar esta seção após cada sessão.**

### Fase 0: ciclo mínimo de pilotagem — CONCLUÍDO (2026-06-10)

`smoke_bridge.py` 5/5 passos OK:
1. Ping via `capture_scene` ✓
2. `list_tree_nodes` — 126 nós na árvore `Biomodelo` ✓
3. `get_node_context` — inspeção de nó real ✓
4. `execute_code` noop (sem mutação) ✓
5. Patch real com alteração + restauração + re-leitura via bridge ✓

### Fase 1: inspeção e mapeamento por região — PRÓXIMA

A árvore `Biomodelo` tem 126 nós / 7 frames (inventário em `docs/CURRENT_TREE_BIOMODEL_INVENTORY.md`):

| Tipo de nó | Qtd | Leitura |
|---|---:|---|
| `ShaderNodeMath` | 51 | cálculos de posição/escala dominam |
| `ShaderNodeCombineXYZ` | 20 | vetores de transformação |
| `GeometryNodeTransform` | 17 | posicionamento de sólidos anatômicos |
| `GeometryNodeMeshCube` | 11 | metacarpal/falange/polegar |
| `GeometryNodeJoinGeometry` | 9 | montagem regional e final |
| `NodeFrame` | 7 | regiões anatômicas |
| `NodeGroupInput` | 5 | pontos de acesso à interface |

**7 regiões:** Antebraço, Polegar, Flex/Ext e Abd Polegar, Desvio e Ext/Flex Punho, Falanges1, Falanges 2, Metacarpos.

**39 parâmetros** — identificadores canônicos em `blender_addon/biomodel/source_template.py`.

**Próximos passos:**
1. Listar nós filhos de cada frame via bridge.
2. Escolher a primeira região para evoluir (candidato: `Antebraço`).
3. Inspecionar a região via bridge (`get_active_frame_context` + `get_node_context`).
4. Propor e executar o primeiro patch real de construção.
5. Verificar, iterar, consolidar apenas quando estável.

### Fases futuras (em espera)

- **Fase 2:** patches incrementais por região.
- **Fase 3:** consolidação de seções validadas em `GN_Biomodel_Source`.
- **Fase 4+:** DSL, helper layer, nodebpy (não implementar agora).

---

## Estrutura ativa

```
blend_IA_ort/
├── blender_connection.py          ← cliente TCP (use este para acessar o bridge)
├── smoke_bridge.py                ← smoke test do ciclo mínimo
├── blender_addon/
│   ├── __init__.py                ← registro: bridge panel + server
│   ├── server.py                  ← TCP bridge (porta 65432)
│   ├── capture.py                 ← snapshots de cena e GN
│   ├── snapshot_manager.py        ← snapshots em marcos
│   ├── project_paths.py           ← resolução de caminhos
│   ├── biomodel/
│   │   ├── source_template.py     ← parâmetros e regiões canônicos (PARAMETERS, REGIONS)
│   │   └── validation.py          ← validação de invariantes do source (ast puro, sem Blender)
│   ├── tools/
│   │   ├── handlers.py            ← HANDLERS — despacho direto sem policy gate
│   │   ├── execution.py           ← handle_execute_code
│   │   ├── reads.py               ← list/find/get_node_context etc.
│   │   ├── snapshots.py           ← capture_scene / capture_full / capture_node_trees
│   │   └── biomodel_source.py     ← read/write/validate/seed biomodel source
│   └── ui/
│       └── bridge_panel.py        ← painel de status do bridge (socket on/off)
├── docs/
│   ├── BIOMODEL_SOURCE_MODE_DECISION.md   ← decisão arquitetural vigente (2026-06-10)
│   ├── BIOMODEL_SOURCE_MIGRATION.md       ← contexto da branch
│   ├── BIOMODEL_AGENT_MIGRATION_PLAN.md   ← plano de fases
│   └── CURRENT_TREE_BIOMODEL_INVENTORY.md ← inventário da árvore (2026-06-03)
└── legacy/                         ← agente embarcado arquivado — ver legacy/LEGADO.md
```

---

## O que NÃO fazer

- **`write_script_draft`** — caminho do agente embarcado. Use `execute_code` no bridge.
- **Rebuild monolítico** — não reescreva o source completo como modo de exploração.
- **`GN_Biomodel_Source` como loop** — é artefato de consolidação pós-validação.
- **Implementar nodebpy agora** — decisão adiada para Fase 4+.
- **Refatorar o agente embarcado** — está em `legacy/`, não é prioridade.
- **`VB_Biomodel_Generated` como referência** — output descartável, pode ser recriado.
- **Mutar `Biomodelo` sem pedido explícito** — é a árvore de referência/desenvolvimento.
