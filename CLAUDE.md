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
| `trace_subgraph(tree_name, seeds, depth=4, direction='back')` | **cone de dependência** com `operation` + índice de socket dos links + defaults (reconstrói fórmulas) |
| `execute_code(code, undo_push=False)` | executa script Python no Blender (retorna `stdout`+`stderr`; var `result` → JSON; `undo_push` registra no undo) |
| `capture_node_trees()` | snapshot de todas as árvores GN |
| `evaluate_geometry(object, sample, region=, diff=, clusters=)` | malha avaliada: bbox, **filtro de região**, **diff entre 2 poses**, **clusters por eixo** (mede escada num call) |
| `render_viewport(object, view, focus=, overlay=, xray=, resolution_x/y=, params=)` | render Workbench → PNG: **foco em região**, **overlay do scan (x-ray)**, pose transitória |
| `reload_addon()` | hot-reload dos módulos de tools (sem restart) após deploy |
| `set_param(object, identifier, value)` | seta input do modifier GN por identifier (com undo_push) |
| `resolve_node(tree, ref)` | resolve nó por **label** ou nome (evita depender de `node.name`) |
| `set_node_input(tree, node, socket, value)` | seta default de socket não-ligado |
| `link_sockets(tree, from_node, from_socket, to_node, to_socket)` | cria link tipado |
| `add_node(tree, bl_idname, name=, label=, location=, operation=, parent=)` | cria nó |
| `read_biomodel_source(block_name)` | lê o source canônico do Text Editor |
| `write_biomodel_source(block_name, code, description)` | escreve source validado |
| `validate_biomodel_source(code)` | valida invariantes sem executar |
| `seed_biomodel_source()` | semente o template fase-1 no Text Editor |

> **2026-06-16:** os handlers de validação/render/mutação estão **ativos** (addon recarregado). `render_viewport` e `evaluate_geometry` foram melhorados (foco/overlay/x-ray; região/diff/clusters), `trace_subgraph` e `reload_addon` foram adicionados, e os handlers de mutação fazem `undo_push`. Detalhes em `docs/BRIDGE_TOOLING_REVIEW_2026-06-16.md`. Deploy = copiar `blender_addon/tools/*.py` p/ `%APPDATA%\...\addons\blender_addon\tools` → `reload_addon()`.

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

### Pose da curva ulnar — REPARO ISOLADO CONCLUÍDO (2026-07-13)

- `Desvio Rad/Ulnar Punho` e `Flex/Ext Punho` já chegavam ao grupo
  `V4_ORT_CurvaUlnar_Lateral_Comprimento`, mas o delta de pose era usado apenas para orientar as
  translações. A geometria da curva ulnar permanecia rígida e, por isso, deixava de acompanhar a mão.
- Foi acrescentado somente o nó matricial `Ulnar_Pose_Aplicada`, entre
  `Ulnar_Combined_Translation` e `Ulnar_Relative_Left`. A ordem preserva os canais existentes e
  aplica à curva o mesmo delta `pose atual × inversa(pose ref)` já usado pela borda radial.
- **Verificação isolada:** sweeps de `+15°` produziram erro máximo de pose `3,44e-5 mm` no desvio e
  `4,83e-5 mm` na flexão/extensão. Os endpoints ulnares permaneceram presos com erro máximo
  `3,08e-5 mm`. Perímetro e comprimento passaram novamente por seus testes anteriores sem regressão;
  pontos, handles e transforms brutos ficaram intactos e nenhum driver ficou inválido.
- Patch: `runtime/patch_v4_ulnar_wrist_pose_only.py`; validação:
  `runtime/validate_v4_ulnar_wrist_pose_only.py`; snapshot anterior:
  `runtime/snapshots/ulnar_wrist_pose_repair/biomodelov4_PRE_ULNAR_WRIST_POSE_20260713T225556.blend`.

### Perímetro lateral ulnar + avanço conjunto por comprimento — CONCLUÍDO (2026-07-13)

- A correção foi limitada aos dois comportamentos confirmados pelo usuário. `Perímetro Punho`
  desloca `V4_ORT_CurvaUlnar_Garra` **somente na direção lateral local**; não acrescenta avanço
  longitudinal nem altera a espessura. O deslocamento usa as larguras já governadas pelo punho:
  `DeltaX = -0,3877699971*DeltaLarguraMC - 0,5*DeltaLarguraOsso`.
- `Mão - Punho até MCP médio` voltou a mover a curva ulnar com a mesma translação rígida 1:1 da
  curva do polegar. Como os oito perfis continuam ancorados entre essas duas bordas, todos avançam
  juntos, sem esticar, girar ou deixar o extremo ulnar preso.
- Os dois canais são independentes no modificador `ORT_Ulnar_Lateral_Comprimento`, usando o grupo
  `V4_ORT_CurvaUlnar_Lateral_Comprimento`: punho atua só no X local ulnar; comprimento atua só no
  Y local antes da conversão pela pose atual do punho. Pontos, handles e transforms brutos das
  curvas foram preservados; erro neutro máximo `3,1e-5 mm`; nenhum driver inválido.
- **Verificação:** sweep de comprimento `104,78 / 124,78 mm` apresentou erro máximo ulnar↔polegar
  `1,1e-5 mm`, dispersão rígida máxima dos perfis `3,2e-5 mm` e erro de extensão `4,6e-5 mm`.
  Sweep de punho `152,71 / 192,71 mm` produziu `±4,393 mm` laterais, com resíduo longitudinal
  local máximo `0,0015 mm` e erro dos endpoints `3,2e-5 mm`. No teste combinado, o erro contra a
  soma independente dos dois movimentos foi `7,1e-6 mm`. Os valores vivos foram restaurados.
- Patch: `runtime/patch_v4_ulnar_lateral_and_hand_length_follow.py`; validação:
  `runtime/validate_v4_ulnar_lateral_and_hand_length_follow.py`; backup anterior:
  `runtime/snapshots/ulnar_lateral_hand_length/biomodelov4_PRE_ULNAR_MINIMAL_20260713T220007.blend`.

### Curva ulnar + ancoragem dos perfis + controle de curvatura — CONCLUÍDO (2026-07-12)

- Criado o objeto `V4_ORT_CurvaUlnar_Garra` na coleção `ORT_Piloto_GN`. A construção inicial com
  oito pontos foi reduzida a uma única Bézier de **dois pontos**, preservando exatamente os
  endpoints dos perfis 01 e 08. Os dois handles livres foram ajustados por mínimos quadrados aos
  seis endpoints intermediários; distância inicial máxima ao shape anterior: `1,83 mm`.
- O desenho manual posterior do usuário foi preservado exatamente. A curva continua livre, azul e
  `show_in_front`, sem modificadores, drivers ou constraints; editar seus pontos, handles ou transform
  agora reposiciona automaticamente os endpoints ulnares dos oito perfis.
- `V4_ORT_PerfilAncorado_MC` ganhou `Object Info (Relative) -> Sample Curve (Factor) -> Set Position`.
  Cada perfil guarda uma estação monotônica por comprimento entre `0,05109` e `0,99868`. A borda
  radial permaneceu imóvel; erro máximo dos endpoints sobre a curva ulnar: `4,6e-5 mm`. Transladar
  a curva 10 mm gerou erro de acompanhamento máximo `1,5e-5 mm`; alterar seu handle moveu as estações.
- Criado o Empty `V4_ORT_CTRL_CurvaturaPalma`, selecionado e bloqueado para movimento somente em Z.
  Ele controla simultaneamente o handle interno radial e o interno ulnar de cada perfil, sem editar
  coordenadas brutas. Ganho 1:1: teste `Z=-10 mm` abaixou o ventre de todas as seções em `7,5 mm`
  (componente vertical `-7,429 mm`) e moveu ambos os endpoints `0,0 mm`.
- Scripts: `runtime/create_v4_ulnar_boundary_curve.py` e
  `runtime/reduce_v4_ulnar_curve_to_two_points.py`. Backup anterior à redução:
  `runtime/snapshots/ulnar_curve_two_points/biomodelov4_PRE_ULNAR_2PT_20260712T184051.blend`;
  backup anterior à criação:
  `runtime/snapshots/ulnar_curve_free/biomodelov4_PRE_ULNAR_CURVE_20260712T183841.blend`.
- Patch de ancoragem/controle:
  `runtime/patch_v4_ulnar_profile_anchor_and_curvature_control.py`; backup imediatamente anterior:
  `runtime/snapshots/ulnar_profile_anchor/biomodelov4_PRE_ULNAR_ANCHOR_20260712T185348.blend`.

### Pose do punho -> rotação conjunta das curvas — CONCLUÍDO (2026-07-12)

- `Desvio Rad/Ulnar Punho` (`Socket_24`) e `Flex/Ext Punho` (`Socket_25`) foram propagados pelo
  objeto longitudinal até os oito perfis. A pose viva **0,02° / -16,14°** é a referência neutra.
- A cadeia replica exatamente o biomodelo: `Rz(desvio)` primeiro, depois `Rx(flexão)`. O delta
  matricial é `M_atual × inversa(M_ref)` e é conjugado pela origem local de cada objeto, fazendo
  todas as curvas girarem ao redor do mesmo pivô global do punho sem alterar transforms de objeto.
- **Verificação:** comparação headless contra o snapshot pré-patch = `0,0 mm` nas nove curvas no
  neutro; sweep de flexão com erro máximo `2,3e-5 mm`; sweep de desvio/pose combinada com resíduo
  máximo de centroide `0,029 mm`; renders top/side confirmam curvas acompanhando a mão nos quatro
  extremos testados. Drivers válidos e pose original restaurada.
- Patch: `runtime/patch_v4_wrist_pose_curve_follow.py`; backup:
  `runtime/snapshots/wrist_pose_curve_follow/biomodelov4_PRE_WRIST_POSE_20260712T165811.blend`.
- **Reintegração após o deslocamento rígido do polegar (mesmo dia):** `Acompanhar_Pose_Punho`
  foi restaurado nos dois grupos e agora vem depois de `Ajustar_Comprimento_Mao_Rigido`:
  `âncora CMC -> comprimento da mão -> pose do punho -> saída`. Sweep `-20°/+20°` moveu as nove
  curvas com erro máximo de forma `6,2e-5 mm`. No teste combinado desvio `+20°` + comprimento
  `135 mm`, polegar e curva diferiram apenas `1,7e-6 mm`. Drivers válidos; pose restaurada em
  `0,02°/-16,14°`. Backup: `runtime/snapshots/wrist_pose_curve_follow/biomodelov4_PRE_WRIST_POSE_20260712T183334.blend`.

### Mão - Punho até MCP médio -> deslocamento do polegar e curvas — CONCLUÍDO (2026-07-12)

- `Socket_161` deixou de escalar/deformar a curva longitudinal. A referência paramétrica continua
  **115 mm**; polegar e curvas usam o mesmo zero, enquanto o valor vivo do slider permanece livre
  e é preservado durante os patches. As coordenadas brutas das curvas não foram alteradas.
- A parametrização anterior da mão continua ativa. Sobre ela, a medida agora acrescenta uma
  **translação rígida** ao polegar já articulado, depois do FK. Assim metacarpo e falanges viajam
  juntos, sem cada segmento herdar uma direção diferente.
- `Polegar - CMC recuo` (`Socket_126`) permanece ligado ao `ThumbCMC_Y` original e continua sendo
  o ajuste fino. O deslocamento da medida é aplicado depois, em `Mover_Polegar_Com_Mao`, portanto
  os dois controles são aditivos e independentes.
- `ORT_PerfilPolegar_Garra` e os oito `V4_ORT_PerfilPalma_*` recebem exatamente a mesma translação
  rígida. Nenhum perfil fica preso ao punho para este parâmetro: todos conservam suas estações
  relativas e acompanham o polegar sem alterar comprimento, largura ou curvatura.
- **Verificação:** sweep `95 / 135 mm` (±20 mm da referência) isolou 24 vértices do polegar movendo como
  bloco, com dispersão máxima `4,6e-5 mm`; as nove curvas tiveram dispersão máxima `2,7e-5 mm` e
  erro de extensão máximo `3,1e-5 mm`. Erro polegar↔curvas `0,0070 mm`. Repetição com o CMC fino
  acrescido de 5 mm alterou a translação em apenas `1,9e-6 mm`. Drivers válidos; valores restaurados.
- Patch: `runtime/patch_v4_hand_length_thumb_translation.py`; validação:
  `runtime/validate_v4_hand_length_thumb_translation.py`; backup anterior a qualquer mutação deste
  lote: `runtime/snapshots/hand_length_thumb_translation/biomodelov4_PRE_THUMB_TRANSLATION_20260712T181350.blend`.
- Histórico supersedido: `runtime/patch_v4_hand_length_curve_follow.py` e snapshot
  `runtime/snapshots/hand_length_curve_follow/biomodelov4_PRE_HAND_LENGTH_20260712T165107.blend`.

### Espessura da palma -> acompanhamento vertical das curvas — CONCLUÍDO (2026-07-12)

- `Espessura da Palma` (`Socket_31`) foi propagada por `V4_ORT_CurvaAncorada_MC` até os oito
  perfis de `V4_ORT_PerfilAncorado_MC`. O neutro vivo de **23,06999 mm** foi preservado.
- As nove curvas acompanham a face palmar inferior pela mesma fórmula da palma viva:
  `DeltaZ = -0,4713219472 * (EspessuraAtual - EspessuraRef)`. O fator combina o movimento do
  centro (`-0,0963219553`) com metade da espessura efetiva dos metacarpos (`0,75/2`).
- **Verificação:** 18 mm -> `+2,38960 mm`; 32 mm -> `-4,20891 mm`; erro máximo
  `2,4e-5 mm`; deslocamento XY `0`; coordenadas e transforms brutos intactos no neutro.
- O perímetro do punho não passou a substituir a espessura: será camada futura de estimativa/preset,
  mantendo override clínico. Estratégia e referências: `docs/PALM_ANTHROPOMETRY_STRATEGY_2026-07-12.md`.
  Patch: `runtime/patch_v4_palm_thickness_curve_follow.py`; backup:
  `runtime/snapshots/palm_thickness_curve_follow/biomodelov4_PRE_PALM_THICKNESS_20260712T163953.blend`.

### Acoplamento punho -> largura da palma + anchor ulnar dos perfis — CONCLUÍDO (2026-07-12)

- No objeto vivo `Sombra_Edu_Garra_D` (`Biomodelo.008`), `Perímetro Punho` virou a medida
  mestra de `Largura Metacarpo` e `Palma - Largura ossos`. Drivers proporcionais preservam o
  caso Edu/Garra como neutro: **148,87999 -> 61,13000 / 18,0 mm**. As três referências ficam
  editáveis nas custom properties `anthro_*_ref_mm` para refinamento com uma coorte futura.
- O grupo `V4_ORT_PerfilAncorado_MC` ganhou expansão transversal local antes do delta matricial
  do polegar. A origem radial de cada perfil permanece fixa e o extremo ulnar segue a variação
  da face externa do metacarpo do mindinho pela fórmula
  `DeltaVao = 0,66777*DeltaLarguraMC + 0,5*DeltaLarguraOsso`.
- Cada um dos 8 perfis guarda seu próprio vão neutro (`Calibracao - Vao ulnar ref`), evitando
  que curvas de comprimentos diferentes recebam deslocamentos diferentes. `Palma - Largura
  ossos` foi propagada pelo barramento `V4_ORT_CurvaAncorada_MC`.
- **Verificação:** neutro preservado em `1,1e-5 mm`; sweep de punho 130 mm recolhe o extremo
  ulnar **6,31795 mm** adicionais e 180 mm expande **10,41391 mm**; erro máximo contra a fórmula
  `5,2e-6 mm`; nenhum driver inválido. Inspeção visual top confirmou abertura apenas ulnar.
- **Recuperação pós-undo + recalibração da face (mesmo dia):** `Ctrl+Z` removeu o lote inteiro
  sem deixar estado parcial; patch reaplicado. O diagnóstico por BVH mostrou que os endpoints
  ulnares neutros antigos estavam **3,8–7,6 mm fora** do proxy. Os 8 endpoints + handles finais
  foram projetados por ray local X na primeira superfície ulnar real e seus vãos-ref atualizados.
  Erro neutro agora `<= 4,9e-5 mm`; sweeps 130/180 ficam `<= 0,93 / 1,82 mm` da superfície
  (resíduo não linear das cabeças MCP). Patch: `runtime/patch_v4_ulnar_endpoint_recalibration.py`;
  backup: `runtime/snapshots/ulnar_endpoint_recalibration/biomodelov4_PRE_ULNAR_RECAL_20260712T033028.blend`.
- Snapshot anterior: `runtime/snapshots/palm_width_coupling/biomodelov4_PRE_PALM_WIDTH_20260712T031405.blend`.
  Patch reproduzível: `runtime/patch_v4_palm_width_coupling.py`. Arquivo vivo salvo em
  `biomodelov4.blend`.
- **Restauro do alinhamento das curvas (2026-07-12):** a comparação com o snapshot pré-recalibração
  confirmou que nenhuma transformação de objeto havia mudado; somente o endpoint ulnar e seus dois
  handles foram deslocados em X local (4,69–7,78 mm). As oito Béziers e seus vãos neutros foram
  restaurados exatamente ao estado `PRE_ULNAR_RECAL`, mantendo intactos os drivers de punho, o
  socket `Palma - Largura ossos` e todo o subgrafo de expansão paramétrica. Patch:
  `runtime/patch_v4_restore_curve_positions.py`; backup:
  `runtime/snapshots/curve_position_restore/biomodelov4_PRE_CURVE_RESTORE_20260712T162328.blend`.

### Limpeza de nós mortos + reapontamento das réplicas — CONCLUÍDO (2026-07-05)

- **Sweep de alcançabilidade** (BFS a partir do Group Output): 20 nós mortos removidos —
  laje da palma inteira (`Cube/TF_Metacarpo1.001`, `Cube_Falange21.001/TF` + feeders
  `AnchorY/NegAnchor/TFVec/SzVec/LargPalma_*`), 2 nós de folga visual e um par
  `Mesh to Volume`/`Volume to Mesh` solto. **161→142 nós**, malha idêntica (Δ=0.0 mm).
  Backup `Biomodelo_PRELIMPEZA_20260705T135644`.
- **Réplicas reapontadas:** `Biomodelo_Edu.001/.002/.003` agora usam a árvore canônica
  `Biomodelo` (63/63 valores preservados por identifier; sockets 124–128 inicializados
  27/10/0/0/1.0; malhas ok). As forks `Biomodelo.001/.002/.004` ficaram sem usuários →
  purgadas no próximo save. `Biomodelo_Edu.004` (experimento v6 de órtese, `Biomodelo.005`)
  ficou intocado. **Polegar das réplicas precisa re-ajuste** (valores antigos compensavam o
  polegar velho).

### Desacoplamento da Espessura da Palma — CONCLUÍDO (2026-07-05)

`Espessura` não engorda mais os dedos nem desloca a mão. Detalhes:
`docs/ESPESSURA_DECOUPLE_2026-07-05.md`. Backup `Biomodelo_PREESPESSURA_20260705T132536`.

- **Socket novo (67→68):** `Dedos - Fator espessura` (Socket_128, default 1.0) — multiplica
  APENAS falanges+polegar (nós locais `EspDedos_*` em 4 frames → 13 ratio-nodes). Palma
  (ossos `Osso_*` via novo `EspProx_Palma = Esp×0.714` cru) e topo-palma seguem Esp crua.
- **Carpo rebaseado no punho:** `Comprimento_Carpo = Punho_raio×1.567586` (era `Esp×1.1`) —
  engrossar a palma não desliza mais a mão em Y.
- **Verificado:** A/B vs backup = 1.1e-05 mm (fator=1); fator 0.7 afina só dedos (×0.6999,
  palma intacta); Esp 40 engorda palma ×1.408 com ponta Y intacta; Esp 40+fator 0.71 = palma
  gorda com dedos idênticos ao ref.
- **Achados:** cubos-laje da palma (`Cube/TF_Metacarpo1.001`, `Cube_Falange21.001/TF`) são
  **nós MORTOS** — palma real são os `Osso_*`; candidatos a sweep de limpeza. Gotcha bridge:
  `execute_code` retorna `result` no topo (`r["result"]`), não aninhado.

### Rebuild do polegar — cadeia CMC anatômica — CONCLUÍDA (2026-07-05)

Polegar reconstruído espelhando a convenção do `FK_Cadeia_Dedo`: grupo novo **`Polegar_FK_v2`**
(44 nós) com raiz na **CMC perto do punho** (paramétrica: `X = Largura_Metacarpo×0.28 + radial`,
`Y = Carpo_raio×−0.5 + recuo`) em vez da base fixa Y=−75 centrada no metacarpo. Cadeia
`Base(CMC) = T·Rz(palmar)·Ry(oposição)·Rz(abd)·Rx(flex)` → metacarpo → junta MCP na **face
distal** → falange prox → junta IP → falange dist. Detalhes: `docs/THUMB_REBUILD_2026-07-05.md`.

- **Sockets novos (63→67):** `Polegar - Ângulo palmar` (124, default 27°), `Polegar - Oposição`
  (125, 10°), `Polegar - CMC recuo` (126), `Polegar - CMC radial` (127), painel `Polegar - CMC`.
  Recabeados (identifiers preservados): 36/37 = flex/abd da **CMC**; 38/39 = flex **MCP/IP**.
  Removidos: rotações de conjunto na origem (`TF_AbducaoPolegar`/`TF_ExtFlexPolegar` + feeders).
- **Verificação por medição:** grupo isolado = previsão analítica com erro 0.0 em 5 poses;
  árvore viva com punho neutro erro máx 0.43 mm; sweeps (flex MCP, oposição, abd, escala
  largura/espessura) todos proporcionais e sem posição fixa. Backup:
  `Biomodelo_PREPOLEGAR_20260705T003112`.
- **Gotchas:** sockets novos ficam 0 nos modifiers existentes (setar via `set_param`);
  Blender 5.1: modo do `GeometryNodeTransform` é input `Mode` = `'Matrix'`; medir o polegar
  exige punho neutro (desvio do punho gira a mão toda) e marcação por segmento.
- **Pendências:** reapontar réplicas forkadas (`Biomodelo.001/.002/.004`) pro canônico + setar
  Socket_124–127; item A do diagnóstico (desacoplar Espessura) aguardando GO; órtese parada a
  pedido; **`.blend` por salvar**.

### Reorganização visual + subgrupos da árvore — CONCLUÍDA (2026-06-16)

A árvore tinha ficado ilegível; reorganizada e enxugada. Detalhes em
`docs/NODE_TREE_REFACTOR_2026-06-16.md`. Snapshot final `runtime/snapshots/polish_done_*`.
Usuário salvou como `biomodelov2.blend` (após a extração do MCP; os polimentos depois disso ficaram
por salvar de novo).

- **Group Input localizado:** o GI global (79 fios cross-frame) virou **cópias locais por frame**
  (sockets não usados ocultos) → cross-frame de GI **88→0**, comprimento de fios **−77%**.
- **Subgrupo `MCP_Cabeca_Dedo`:** frame MCP (71 nós) → **4 instâncias** + comuns. 14 inputs (4
  constantes por-dedo promovidas: arco/X/curvatura/coroaY). Verificado vértice-a-vértice (7/1746
  diferem ≤0.1 mm = float). **Gotcha:** `group_make` não promove constantes internas, e não propaga
  default de interface a instâncias existentes (Indicador ficou 0.0 → corrigido).
- **Subgrupo `Polegar_FK`:** frame FK Polegar (32 nós) → **1 instância** (fingerprint idêntico).
- **Subgrupo `Dedo_Falanges`:** a geometria de falange dos 4 dedos → **4 instâncias** (10 inputs:
  Largura + Comp/Esp/Matriz × prox/média/distal). Exigiu **modernizar Indicador+Anelar** (estilo
  legado das 2-cadeias) pro estilo novo: o tracer captura as fontes reais (largura do slider p/
  Indicador, fixa p/ os outros; Z=Espessura×ratio; matrizes do FK) → instância. Fingerprint
  idêntico nos 4. Depois um sweep de nós-mortos tirou 16 resquícios (`AlignVec_*`, `BaseVec_*`,
  `BaseXr_*`, `FingersCenterX`, `Math.031/036-046`). Posicionamento dos dedos é via FK `Base X`
  (os transforms `Pos`/`Centra dedos` eram identidade).
- **Layout:** engine `runtime/relayout_biomodel.py` (grade 3-fileiras por fluxo + barycenter pra
  reduzir cruzamentos); cores por fileira; polegar puxado pra fileira do meio.
- **Total: 277 → 138 nós.** Grupos: `FK_Cadeia_Dedo`, `MCP_Cabeca_Dedo`, `Polegar_FK`,
  `Dedo_Falanges` (todos com 4 instâncias, exceto Polegar=1). Geometria intacta (1746 verts) em
  todas as etapas. Snapshot final `runtime/snapshots/dedo_falanges_done_*`. **`.blend` por re-salvar**
  (v2 foi salvo antes destas extrações).

### Ajuste lateral (X) dos pivôs MCP por dedo — CONCLUÍDA (2026-06-16)

Família de controle gêmea do `Avanço MCP`, mas no eixo **lateral (X)**: ajuste fino por dedo de
quão "para dentro/fora" cada cabeça/elipse MCP (e o dedo ancorado nela) fica. Detalhes em
`docs/MCP_LATERAL_CONTROL_2026-06-16.md`.

- **Onde entra:** o lateral soma em `MCP_X_Final_<dedo>`, que já alimenta **esfera** (`MCP_Pos.X`)
  **e** base do dedo no FK (`Base X`) da mesma fonte → move a articulação no mundo (anti-escada);
  X é o eixo da flexão → **imune à flexão** (dz=0). 8 nós novos (`MCP_Lateral_*` + `MCP_X_AjusteLat_*`).
- **Sockets novos (58→63):** `Dedos - Lateral MCP geral` (Socket_118) + por-dedo
  Indicador/Médio/Anelar/Mindinho (Socket_119–122), painel *Dedos - MCP / Pivôs*, range −40..40,
  default 0. Positivo = lado radial/polegar. `source_template.py` + `presets/biomodel_sockets_live.json`
  atualizados (63 sockets).
- **Verificado por medição:** zero-regressão a 0; offset por dedo move exatamente 290 verts (geral =
  4×290); slider −15 → translação rígida de módulo **15.000 mm**, **dz=0**, idêntica a 90° de flexão.
- **Gotcha:** comparar nós bpy com `==`/`.name`, nunca `is` (wrappers novos a cada acesso geraram um
  self-loop no 1º patch). Painel real chama-se `Dedos - MCP / Piv?s` (typo `?`); há um painel vazio
  homônimo com `ô` — limpeza opcional.

### Cinemática MCP dos dedos longos + ancoragem nas esferas — CONCLUÍDA (2026-06-16)

Conserto da "escada" de altura na flexão a 90° + dedos partindo da borda das esferas MCP.
Detalhes completos em `docs/MCP_FINGER_KINEMATICS_2026-06-16.md`. Snapshot:
`runtime/snapshots/mcp_finger_kinematics_20260616/biomodel_mcp_fixed.blend`.

- **Causa-raiz:** o offset por-dedo era aplicado no referencial **local que gira com a flexão** →
  a 90° virava deslocamento vertical, e como diferia por dedo, gerava escada. **Invariante nova:**
  posição por-dedo move a **articulação no mundo** (pivô/esfera, que não gira); só **folga uniforme**
  pode viver no referencial local do dedo.
- **Arquitetura:** pivô = esfera = base da falange, todos em `MCP_Guide_Ponta + MCP_Avanco_Total`
  (arco anatômico: Médio mais avançado). Nova entrada **`Base X`** no grupo `FK_Cadeia_Dedo` coloca
  o dedo no X da esfera; translações pós-FK (`TF_CenterFingers_*`, `Pos_D3/D5`) zeradas. Folga
  base↔esfera **uniforme e paramétrica** = raio da esfera (`Punho_raio×0.432`) + 2.5 mm (`FK_GapEdge`).
- **Removidos:** sliders `Dedos - Offset MCP` (geral + 4 por-dedo, Socket_104–108) e nós
  `MCP_Offset_Efetivo_*` — eram a causa da escada. Demais sockets mantiveram seus identifiers.
- **Controles agora:** longitudinal global = `Comp Metacarpo`; avanço/arco por-dedo = `Avanço MCP`
  (livre de escada, mexe na articulação); direção = `Abdução`. Verificado: spread das pontas a 90°
  = **0.0 mm**, e imune a ajuste por-dedo (mindinho +15 mm → spread continua 0.0).
- **Aprendizado de backend:** os handlers de validação/render do repo **não estavam ativos** no
  Blender ligado (addon stale); tive que reimplementar render/medição via `execute_code`
  (`runtime/inspect/`). Revisão e plano em `docs/BRIDGE_TOOLING_REVIEW_2026-06-16.md`. Undo do
  usuário reverteu edições do bridge algumas vezes — **salvar após marcos** é crítico.

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
