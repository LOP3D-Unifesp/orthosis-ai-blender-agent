# Revisão de ferramentas / backend do bridge — pós-sessão MCP (2026-06-16)

Levantado a partir do atrito real ao consertar a cinemática dos dedos. Ordenado por impacto.

## ✅ Status: IMPLEMENTADO (2026-06-16)

Tudo abaixo foi implementado e está vivo no addon (deploy + reload verificados):

- **P0.1** — addon recarregado; handlers de validação/render ativos + `execute_code` devolve `result`.
  Novo comando **`reload_addon`** (hot-reload dos módulos de tools, sem restart) em `handlers.py`.
- **P0.2** — `undo_push` adicionado aos 4 handlers de mutação (`set_param`/`set_node_input`/
  `link_sockets`/`add_node`) e flag opcional `undo_push` no `execute_code`.
- **P1.3** — `render_viewport` agora aceita `focus` (janela de região), `overlay`+`xray` (scan),
  `resolution_x/y`, `keep`, `params` (pose transitória, restaurada), e restaura a câmera/engine/shading.
- **P1.4** — `evaluate_geometry` agora aceita `region` (filtro), `diff` (dois estados de parâmetro →
  verts movidos, com restore) e `clusters` (k grupos por eixo + `cluster_spread`). O teste de escada
  virou **uma chamada**.
- **P1.5** — novo handler **`trace_subgraph`** (BFS direcional com `operation` + índice de socket dos
  links + defaults); links em `_serialize_nodes_and_links` ganharam `from/to_socket_index`.
- **P2.6** — cliente ganhou `BlenderConnection.save_json()` (escreve UTF-8 em arquivo, evita o
  cp1252 do console do Windows).

Cliente (`blender_connection.py`): novos métodos `trace_subgraph`, `reload_addon`, `save_json`, e
pass-through dos novos params em `render_viewport`/`evaluate_geometry`. Backups `.bak` dos arquivos
instalados em `%APPDATA%\...\addons\blender_addon\tools`.

Pendente (P2.7): helper "comparar contra referência" — não implementado (cobre-se hoje com
`evaluate_geometry diff/region` + `render_viewport overlay`).

---

## Diagnóstico original (mantido para histórico)

## P0 — Resolver já (alto impacto, baixo custo)

### 1. O addon rodando está DESATUALIZADO
Os handlers `render_viewport`, `evaluate_geometry`, `set_param`, `resolve_node`, `set_node_input`,
`link_sockets`, `add_node` **existem no repo** (`blender_addon/tools/validation_tools.py`,
registrados em `HANDLERS`) mas retornam erro no Blender ligado — a instância carregou uma cópia
antiga. O `execute_code` rodando também é antigo: **não devolve a variável `result`** (tive que
`print("__JSON__"+json.dumps(...))` e parsear stdout o tempo todo).

- **Ação:** recarregar o addon (reabrir o .blend / re-registrar / restart) para ativar tudo. Isso
  sozinho elimina ~80% dos helpers que tive que escrever nesta sessão.
- **Melhoria estrutural:** um comando `reload_addon` no bridge (re-`importlib.reload` dos módulos de
  tools + re-registro) para não depender de restart manual — hoje "ativa no próximo restart" é uma
  pegadinha recorrente registrada no CLAUDE.md.

### 2. UNDO desfaz minhas edições (risco de perda de trabalho)
Edições via bridge não entram no undo stack do Blender de forma consistente; o `Ctrl+Z` do usuário
reverteu várias vezes mutações minhas (relink de grupo, sphere reconnect). Perdi e refiz trabalho.

- **Ação:** chamar `bpy.ops.ed.undo_push(message=...)` ao final de cada mutação (ou batch) nos
  handlers de mutação, **ou** auto-snapshot (`save_as_mainfile(copy=True)`) após cada batch.
- **Mínimo:** o bridge avisar no response quando detecta que o estado divergiu do esperado.

## P1 — Próxima rodada (fecha lacunas que me forçaram a improvisar)

### 3. `render_viewport` é limitado para validação real
O handler atual: 1 objeto isolado, enquadra o objeto inteiro, quadrado, sem overlay. Para validar
contra o scan eu precisei reescrever (`runtime/inspect/render.py`). Faltam:
- **Janela de foco** (recortar uma região, ex. só os dedos `ylo:yhi`) — senão o antebraço domina o
  quadro e os dedos somem.
- **Overlay de referência** (mostrar `Scan_Edu_MaoEspalmada` junto, em **x-ray**) — essencial pra
  calibrar contra o scan. (`scene.display.shading.show_xray + xray_alpha`.)
- Resolução **não-quadrada** e lista de objetos a manter visíveis.
- Câmera **fixa** opcional (mesmo enquadramento entre dois renders pra comparar lado-a-lado).

### 4. `evaluate_geometry` só dá bbox/samples do objeto inteiro
Para medir "altura da ponta de cada dedo" tive que avaliar a malha, achar verts que se movem entre
2 poses e clusterizar por X (ruidoso). Faltam:
- **Filtro de região** (avaliar só verts dentro de um bbox/eixo).
- **Diff entre dois estados de parâmetro** (verts que se moveram > t).
- **Estatística por cluster** (k grupos no eixo X/Y).
- Ideal: **ler valor avaliado de um socket/campo** ou **a geometria de saída de um nó** específico.
  Não conseguir isso me empurrou pra contas analíticas das fórmulas dos nós — que **erraram** (minha
  posição "analítica" das esferas estava ~20 mm fora da real).

### 5. Leitura de grafo: `get_node_context` esconde o que importa
Não expõe a `operation` dos `ShaderNodeMath`, nem o **índice do socket** de cada link (qual entrada
recebe), nem os `default_value`. Sem isso não dá pra reconstruir a fórmula. Tive que escrever um
tracer BFS-reverso (`runtime/inspect/trace.py`) que captura exatamente isso.
- **Ação:** dobrar `operation`, `from_socket_index`/`to_socket_index` e defaults dentro de
  `get_node_context`/`find_tree_nodes`, e adicionar um `trace_subgraph(seed, depth, dir)`.

## P2 — Conforto / robustez

### 6. Encoding do console (Windows cp1252)
`print()` no cliente quebra com Unicode (emoji/acentos dos labels). Tive que rotear tudo por arquivo
JSON. Convenção no cliente: helpers que **escrevem em arquivo** (UTF-8) em vez de imprimir, ou
`PYTHONIOENCODING=utf-8` documentado, ou `ensure_ascii=True` no lado Blender + decode no cliente.

### 7. Helper de "comparar contra referência"
Calibração contra scan é recorrente (antropometria). Um handler que compara objeto avaliado vs.
objeto de referência por região (offset/escala) automatizaria o loop que fiz na mão.

## O que JÁ funciona bem (manter)
- `execute_code` é poderoso o suficiente pra construir qualquer um dos helpers acima por cima — foi
  o que salvou a sessão. Os padrões reutilizáveis ficaram em `runtime/inspect/` (`dump.py`,
  `trace.py`, `dumpgroup.py`, `render.py`) e são bons candidatos a virar handlers de primeira classe.
- Endereçar nós/sockets por **nome** (não por `Socket_N`, que renumera no rebuild) — invariante já
  documentada, e que me salvou ao remover sockets sem quebrar os demais.

## Resumo executivo
A maior parte do meu atrito foi **não ter as ferramentas que já existem no repo ativas** (P0.1) e
**não conseguir medir geometria avaliada com precisão** (P1.4/P1.5), o que me fez cair em contas
analíticas frágeis. Resolver P0 + P1.4/5 transformaria o loop "alterar→observar→medir" de horas de
helpers ad-hoc em chamadas diretas.
