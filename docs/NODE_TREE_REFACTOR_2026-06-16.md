# Reorganização + subgrupos da árvore `Biomodelo` — 2026-06-16

Branch `codex/biomodel-source-migration`. Objetivo: a árvore tinha ficado ilegível
(órfãos, frames sobrepostos, e o `Group Input` global espalhando fios por tudo). Salva pelo
usuário como `biomodelov2.blend` após a extração do MCP.

## O que foi feito (em ordem)

1. **Re-emolduramento + grade** (`runtime/relayout_biomodel.py`): 56 nós órfãos emoldurados; os
   dois dedos soltos (Médio=`*_D3`, Mindinho=`*_D5`) viraram frames próprios; frames numa grade de
   3 fileiras por fluxo de dados.
2. **Group Input localizado**: o `Group Input` global (80 consumidores, 79 cross-frame) foi quebrado
   em **cópias locais por frame** (sockets não usados ocultos). Cross-frame de GI: **88 → 0**;
   comprimento total de fios de GI **−77%**. 3 GIs mortos apagados. O MCP ainda foi dividido em 4
   cópias por dedo.
3. **Subgrupo `MCP_Cabeça_Dedo`** (`MCP_Cabeca_Dedo`): o frame MCP (71 nós) virou **4 instâncias** +
   ~6 nós comuns. Fronteira limpa (5 in / 14 out). 14 entradas, sendo **4 constantes por-dedo
   promovidas** a inputs (fator de arco, X, curvatura, coroa Y) — senão os dedos colapsam.
   Verificado vértice-a-vértice: 7/1746 verts diferem por ≤0.1 mm (ruído de float na fronteira).
   Bug pego no caminho: a instância Indicador (criada pelo `group_make`) ficou com as 4 constantes
   em 0.0 (Blender não propaga default de interface a instâncias existentes) — corrigido setando na
   instância.
4. **Tidy interno** (barycenter / Sugiyama no engine): ordenação vertical dos nós dentro de cada
   coluna de profundidade pra reduzir cruzamento de fios (6 sweeps).
5. **Cores por fileira**: backbone (azul-acinzentado), palma+MCP+polegar (verde), 4 dedos (marrom).
6. **Subgrupo `Polegar_FK`**: o frame FK Polegar (32 nós, cadeia única) colapsado em **1 instância**
   (6 in / 3 out). Fingerprint idêntico (sem constantes por-instância pra promover).

**Resultado:** `Biomodelo` **277 → 194 nós**. Grupos reutilizáveis: `FK_Cadeia_Dedo` (4 dedos),
`MCP_Cabeca_Dedo` (4 cabeças), `Polegar_FK` (1). Geometria intacta em todas as etapas (1746 verts,
bbox idêntico).

## Ferramenta reproduzível

`runtime/relayout_biomodel.py` lê `runtime/inspect/tree_full_graph.json` (dump de nós+links),
atribui região por frame/nome, faz grade interna por profundidade + barycenter, tila os frames numa
grade 3-fileiras (`GRID`), valida zero sobreposição, e grava `layout_plan.json`. O apply (unparent →
coords absolutas → reparent com frames em (0,0)) está nos scripts de bridge da sessão. Re-rodar
após mudanças na árvore re-tidia tudo.

## Gotchas reforçados

- **bpy: comparar nós/sockets com `==`/`.name`, nunca `is`** (wrappers novos a cada acesso). Causou
  self-loop e votos de vizinhança vazios em passos anteriores.
- **Posição de filho de frame é renormalizada no redraw** → layout programático: unparent → abs →
  reparent com frame em (0,0).
- **`group_make` não promove constantes internas** — diferenças por-instância viram inputs à mão.
- **Append de node group re-atribui identifiers `Socket_N`** → comparar/mapear por NOME, não id.
- **`evaluate_geometry` pode vir de eval stale** — verificação real usa `obj.update_tag()` +
  `to_mesh()` + fingerprint de verts ordenados (independente de ordem do join).

## Snapshots
`runtime/snapshots/`: `pre_node_relayout_*`, `pre_mcp_group_*`, `mcp_group_done_*`,
`mcp_group_regrid_*`, `polish_done_*`.
