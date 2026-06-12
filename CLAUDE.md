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
| `execute_code(code)` | executa script Python no Blender (agora retorna `stdout`+`stderr`; opcional var `result` → JSON) |
| `capture_node_trees()` | snapshot de todas as árvores GN |
| `evaluate_geometry(object, sample=N)` | malha avaliada: vcount, bbox, amostras (validação numérica) |
| `render_viewport(object, view='iso')` | render Workbench → PNG (validação visual; views: top/front/side/iso) |
| `set_param(object, identifier, value)` | seta input do modifier GN por identifier |
| `resolve_node(tree, ref)` | resolve nó por **label** ou nome (evita depender de `node.name`) |
| `set_node_input(tree, node, socket, value)` | seta default de socket não-ligado |
| `link_sockets(tree, from_node, from_socket, to_node, to_socket)` | cria link tipado |
| `add_node(tree, bl_idname, name=, label=, location=, operation=, parent=)` | cria nó |
| `read_biomodel_source(block_name)` | lê o source canônico do Text Editor |
| `write_biomodel_source(block_name, code, description)` | escreve source validado |
| `validate_biomodel_source(code)` | valida invariantes sem executar |
| `seed_biomodel_source()` | semente o template fase-1 no Text Editor |

> Os handlers de validação/mutação (`evaluate_geometry`, `render_viewport`, `set_param`, `resolve_node`, `set_node_input`, `link_sockets`, `add_node`) foram adicionados em 2026-06-12 (`blender_addon/tools/validation_tools.py`). **Ativam no próximo restart do Blender** — o addon não recarrega a quente. Na sessão atual o mesmo efeito é obtido via `execute_code`.

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

### Fase 3 — consolidação no GN_Biomodel_Source — CONCLUÍDA (2026-06-12)

**`GN_Biomodel_Source` v1 registrado no Text Editor** (629 linhas, validação 0 erros / 0 warnings) e commitado no repo em `biomodel_source/GN_Biomodel_Source_v1.py`. Executá-lo no Blender cria/substitui apenas `VB_FK_Cadeia_Dedo` + `VB_Biomodel_Generated` (ambos com fake_user; existem no .blend salvo).

- **Formato**: data-driven — tabelas (INTERFACE com 5 painéis/41 sockets, GROUP_NODES/LINKS do grupo FK, NODES/LINKS da árvore) + motor de construção (~100 linhas). Defaults = valores clínicos do modifier no momento da consolidação (afinados pelo usuário contra o scan).
- **Verificação**: árvore gerada em objeto temporário reproduz a árvore viva **vértice a vértice** em 4 poses com o vetor completo de 41 parâmetros fixado (desvio 1e-4).
- **Armadilhas resolvidas (gerador)**: (1) sockets de Group Input/Output e instâncias de grupo endereçados por **nome** — identifiers `Socket_N` são re-atribuídos a cada rebuild; (2) ordem de join multi-input vem de `link.multi_input_sort_id`, **não** da ordem de `tree.links` — sem isso os vértices permutam; (3) verificação precisa fixar todos os parâmetros, não só os de pose.
- Pipeline de re-geração: extração (serializa árvore p/ JSON) → gerador local → verificação por regressão → `write_biomodel_source`. Scripts temporários removidos; recriáveis a partir deste registro.

### Refatoração + organização visual — CONCLUÍDA (2026-06-12, noite)

Árvore `Biomodelo` otimizada e organizada, **salva** em `testeAgenteBlender1.blend`. Snapshot pré-refatoração: `runtime/snapshots/param_v1_20260612/param_v1_validada.blend`. Regressão verificada a cada patch: malha avaliada idêntica em 4 poses (atual/zeros/fechada/espalmada, desvio ≤ 5e-5).

1. **Node group `FK_Cadeia_Dedo`** (46 nós internos): as cadeias gêmeas F1/F2 (38 nós cada + 12 feeders) viraram **2 instâncias** de um grupo único. Inputs: Ponta MC, Comp Prox/Media/Dist, Flex Prox/Media/Dist (graus), Abducao (graus), Direcao Abd (−1 radial / +1 ulnar). Outputs: 3 matrizes (`Matriz Prox/Media/Dist`) → `Transform Geometry` modo Matrix. Editar a cinemática do dedo = editar o grupo uma vez.
2. **Dedup de Math**: 8 nós DIVIDE idênticos fundidos (`Math.003`→`Math`; `Math.033–045`→`Math.031`).
3. **Total**: 219 → **133 nós / 183 links** na árvore principal (+ grupo 46/57). Zero nós soltos, zero links inválidos.
4. **Layout**: 12 frames em grade global 3 fileiras (Entradas→Cálculos→Antebraço→Punho→Montagem / Metacarpos→FK Dedos→Dedo 1→Dedo 2 / FK Polegar→Polegar Primitivas→Rotações Polegar). Re-grade interna por profundidade de dependência. **GI locais por frame** (`GI_F0xx`, `GI_FK_*`, sockets não usados ocultos) eliminaram os 35 fios longos (>2500px). Frames novos: `Frame_FK_Dedos`, `Frame_FK_Polegar`. Labels renomeados: `Dedo 1 (radial)` / `Dedo 2 (ulnar)`.
5. **Aprendizado de API**: posição de nó filho de frame é renormalizada pelo Blender no redraw — para layout programático, desparentar → coordenadas absolutas → mover → reparentar com frame em (0,0).
6. Fusões de Transform sequenciais (punho/CMC polegar) avaliadas e **descartadas** — trocariam 1 nó por 3.

### Polegar FK + abdução dos dedos — CONCLUÍDA (2026-06-12, tarde)

Parametrização v1 do biomodelo **completa**. Árvore `Biomodelo`: **219 nós / 281 links / 0 inválidos**, **41 parâmetros**. `.blend` ainda não salvo após esta sessão (marco de snapshot pendente).

1. **Polegar migrado para FK matricial** (26 nós `FK_TH_*`): `ctBase` (frame do metacarpo, T=(27.1,−85.25,0), Rz=0.473) → junta MCP → junta IP, flexão em **eixo Z** (plano da palma; dedos longos usam X). `TF_Polegar1/2/3` em modo Matrix. Offsets de cubo **derivados dos comprimentos** (sockets 33/40/43) — paramétrico, não constante. Sinal negado na entrada (`FK_TH_negFlexProx/Dist`) para manter positivo = fechar; isso **inverteu a direção** dos sliders 38/39 vs comportamento antigo. Validado: cluster do cubo distal bate com a previsão analítica da cadeia (erro 0.0).
2. **Abdução dos dedos longos** (12 nós `FK_F1/F2_abd*` + sockets `Abdução Dedo 1` = `Socket_76`, `Abdução Dedo 2` = `Socket_77`, graus, range −15..45, positivo = abrir): `M0 = T(j0)·Rz(abd)·Rx(flex)`. A "escada" de offsets X dos cubos (F1: −14.6/−29.8/−47.3; F2: 8.2/16.6/17.0) foi **zerada** — o leque agora é rotação real na junta (cubos angulados na direção do dedo, como o scan espalmado). Defaults 28.6°/10° reproduzem o leque antigo. Pivô do leque: `j0` em X=0 (centro da palma, como na sintonia original).
3. `source_template.py` atualizado com os 2 novos parâmetros (41 canônicos).

### Consolidação + limpeza — CONCLUÍDA (2026-06-12)

`Biomodelo` é agora a **árvore canônica** (181 nós / 235 links / 0 links inválidos), salva em `testeAgenteBlender1.blend`. É um **biomodelo puro** — sem nenhum nó de órtese. Detalhes em `docs/CONSOLIDATION_2026-06-12.md`.

O que mudou:

1. **Flexão dos dedos longos consertada (cinemática).** As duas cadeias (dedo 1 = radial, dedo 2 = ulnar) foram migradas para **forward kinematics matricial** MCP→PIP→DIP (`CombineTransform`+`MatrixMultiply`+`EulerToRotation`, eixo **X**), padrão do polegar de `Geometry Nodes.001`. Nós com prefixo `FK_F1_`/`FK_F2_`. Sinal positivo = fechar a mão.
2. **Flexão dos dedos consertada (unidades).** Os sockets de flexão (47/48/49, 60/61/62 e polegar 38/39) tinham subtype `ANGLE` (UI em graus, valor em **radianos**) e o nó `RADIANS` convertia de novo → dupla conversão, dedo quase não mexia no slider. Corrigido: subtype `NONE`, valor = **graus diretos**, range de slider −20..110. Punho fechado validado com MCP 85° / PIP 95° / DIP 50°.
3. **Órtese removida por completo** (decisão 2026-06-12): o protótipo de calha (`ORT_*`) ficou ruim e foi descartado junto com as âncoras (`ANC_*`) e os 4 sockets `Ortese:*` da interface. A órtese será reconstruída depois, num passo próprio, a partir do sistema de curvas da árvore `Geometry Nodes`.
4. **Matemática morta purgada**: 28 nós do antigo posicionamento de tradução dos dedos (`Combine XYZ.002–.007`, `Math.007–.028`) removidos. `Math.006` (`PontaMC_Base`) permanece — alimenta o FK.

**Status das outras árvores:**
- `Geometry Nodes.001` (80 nós, obj `devbiomodelo`) — **referência histórica** do padrão FK matricial do polegar.
- `Geometry Nodes` (100 nós, obj `luizbiomodelo`) — sistema de curvas da órtese + scan real. **Referência** para a futura reconstrução da órtese.
- `Biomodelo_BACKUP_20260612T034627Z` (145 nós, fake_user) — árvore pré-consolidação. Backup em disco: `runtime/snapshots/consolidation_20260612T034627Z/pre_consolidation.blend`.

**Pendências conhecidas:**
- ~~Polegar em `Biomodelo` no modelo antigo~~ — resolvido (sessão 2026-06-12 tarde, FK matricial `FK_TH_*`).
- Offset Y de centro do cubo nos dedos longos (`FK_F1/F2_offv*`) ainda vem de `negHalf*` ligado aos comprimentos — OK; a posição da base (`Math.006`/PontaMC) segue constante em X=0.
- Órtese: reconstruir do zero ligada a âncoras do biomodelo, partindo das curvas Bezier de `Geometry Nodes` (não reaproveitar o protótipo de calha descartado).

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
