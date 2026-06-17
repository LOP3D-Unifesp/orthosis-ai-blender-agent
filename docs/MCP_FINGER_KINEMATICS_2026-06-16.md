# Cinemática MCP dos dedos longos — conserto da flexão + ancoragem nas esferas (2026-06-16)

Branch: `codex/biomodel-source-migration`. Árvore viva `Biomodelo`, objeto `Biomodelo_Edu`,
referência visual `Scan_Edu_MaoEspalmada`. Snapshot do estado final:
`runtime/snapshots/mcp_finger_kinematics_20260616/biomodel_mcp_fixed.blend`.

## Sintoma

Ao flexionar `Dedos - Flex/Ext proximal geral` a 90°, a **altura** das falanges ficava em
"escada" (cada dedo num nível diferente, com folgas distintas abaixo das esferas MCP). Ajustar
os sliders `Dedos - MCP / Pivôs` (offset por dedo) reposicionava no repouso mas **trazia a escada
de volta** na flexão. Além disso o comprimento do metacarpo arrastava esferas e dedos de forma
não-linear (sobreposição com valores grandes).

## Causa-raiz (a regra que destravou tudo)

O offset por-dedo era aplicado **dentro do referencial local do dedo, que gira com a flexão**
(grupo `FK_Cadeia_Dedo`: `MCP_offset_neg` → `MCP_prox_center_Y` / `MCP_pip_joint_Y`, ao longo do
−Y local). A 0° isso parece só uma folga pra frente; a 90° esse −Y local vira **−Z (vertical)**, e
como cada dedo tinha um offset diferente (Index 29, Médio 23, Anelar 32, Mindinho 18 mm), cada base
caía uma altura diferente → escada.

> **Invariante de projeto:** posicionamento **por-dedo** tem que mover a **articulação no espaço
> de mundo** (pivô/esfera — que **não** gira com a flexão). Só uma **folga uniforme** pode viver no
> referencial local do dedo. Mundo não inclina a flexão ⇒ não há como gerar escada.

A não-linearidade era o mesmo bug por outro ângulo: as esferas liam Y de uma cadeia
(`MCP_Guide_Ponta = base × fator`) e as bases dos dedos de outra (`PontaMC + offset`), com
inclinações diferentes → divergiam ao crescer o metacarpo.

## Arquitetura final

Para cada dedo, a **articulação MCP é um único ponto** que serve simultaneamente de centro de
esfera e de **pivô de flexão**, posicionado no mundo por:

- **Y (avanço):** `MCP_Guide_Ponta = (Punho_raio + Comp Metacarpo) × fator_arco`, com fatores de
  arco anatômicos por dedo — **Médio 1.102** (mais avançado), Indicador 1.063, Anelar 1.039,
  Mindinho 0.933. Trim por-dedo opcional via `Avanço MCP` (geral + por-dedo + curvatura) — entra
  na **posição da articulação**, então é **livre de escada**.
- **X (lateral):** `MCP_X_Final = Largura Metacarpo × fator_X` — agora **alimentado para dentro do
  grupo FK** via a nova entrada **`Base X`** (`j0v.X`), de modo que o dedo nasce no X da esfera.
  As translações pós-FK que existiam (`TF_CenterFingers_F1/F2`, `Pos_D3/D5`) foram **zeradas** —
  eram uma cadeia lateral separada que desalinhava a base ~15–20 mm.
- **Folga base↔esfera (uniforme):** o offset local agora é **um único valor uniforme**,
  paramétrico = **raio da esfera (`Punho_raio × 0.432` ≈ 9.6 mm) + 2.5 mm** (nó `FK_GapEdge`),
  alimentando os 4 dedos igualmente. Assim a falange começa na **borda distal da esfera** (não no
  centro), simulando a biomecânica da junta sem encurtar o dedo — e por ser uniforme, **não escada**.

Pivô = esfera = base, todos na mesma fonte. `Comp Metacarpo` move tudo junto, linear.

## O que mudou na árvore `Biomodelo`

1. Grupo `FK_Cadeia_Dedo.001`: nova entrada **`Base X`** ligada a `j0v.X`.
2. `MCP_PontaMC_Efetivo_<dedo>` agora soma **`MCP_Guide_Ponta` + `MCP_Avanco_Total`** (era
   `Math.006`/base) e alimenta **pivô (FK "Ponta MC")** e **esfera (`MCP_Pos.Y` via `MCP_Y_Neg`)**.
3. Cada FK recebe `Base X = MCP_X_Final_<dedo>`; `TF_CenterFingers_F1/F2` e `Pos_D3/D5` com
   translação **(0,0,0)**.
4. **Removidos:** sliders `Dedos - Offset MCP geral` + 4 por-dedo (Socket_104–108) e os nós
   `MCP_Offset_Efetivo_*`. (Os demais sockets mantiveram seus identifiers — `presets/` e o addon
   de antropometria não referenciam os removidos.)
5. Folga uniforme via `FK_GapEdge = MCP_RaioVisual_Efetivo + 2.5`, ligada às 4 entradas `Offset MCP`.

## Verificação objetiva

- **Spread da altura das pontas a 90° = 0.0 mm** (as 4 a Z=44.1).
- **Teste de imunidade:** empurrar o Mindinho +15 mm no `Avanço MCP` → spread continua **0.0 mm**.
  (Era exatamente esse ajuste por-dedo que reintroduzia a escada no esquema antigo.)
- Repouso casa com o scan: ponta do dedo médio em Y=−219.4 vs scan −218.7 (`Comp Metacarpo` 90).
- Esferas visíveis na linha dos nós, falanges partindo da borda distal.

## Esquema de controle resultante (dedos longos)

| Intenção | Controle | Escada? |
|---|---|---|
| Posição longitudinal global dos nós | `Comp Metacarpo` | não |
| Avanço/arco por-dedo (mexe na articulação) | `Avanço MCP` geral / por-dedo / `Curvatura arco MCP` | **não** |
| Direção do dedo (leque) | `Abdução` geral / por-dedo | não |
| Folga base↔esfera (uniforme, biomecânica) | `FK_GapEdge` (raio + 2.5; hoje não exposto como slider) | não |
| ~~Offset/Pivô por-dedo~~ | **removido** (causava a escada) | — |

## Pendências / próximos

- Afinar abduções por-dedo contra o scan (Index −10, Médio 0, Anelar −13, Mindinho −22 como ponto
  de partida desta sessão; bom o suficiente segundo o usuário).
- "leve offset" de 2.5 mm e os fatores de arco/`Base X` estão como constantes de nó — promover a
  sliders limpos se o usuário quiser controlá-los.
- Mindinho "mais pra dentro" (lateral) ficou pendente por escolha do usuário.
