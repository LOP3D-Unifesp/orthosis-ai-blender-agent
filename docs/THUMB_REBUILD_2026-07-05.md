# Rebuild do polegar — CMC anatômica (2026-07-05)

## Problema (diagnóstico via bridge)

O grupo `Polegar_FK` (34 nós) tinha o esqueleto certo (metacarpo + falange prox + dist),
mas **enraizado errado**:

- Base `ThumbBaseVec = (Largura_Metacarpo × 0.379, Y = −75.0 FIXO, Z = 0)`, rotação base
  `Rz = 0.473 rad (27.1°) FIXO`.
- O cubo do metacarpo é **centrado nessa base fixa**; a junta MCP fica a −CompMC/2.
- Y=−75 é bem **distal** (perto das cabeças dos metacarpos), quando a CMC anatômica
  (trapézio) fica **perto do punho**. Como Y=−75 não escala com a mão, em mão pequena a base
  cai fora da palma → o usuário encolhe `Comp Metacarpo` (11.86 numa réplica) para compensar.
  O comprimento virou fator de correção, não medida.
- `Flex/Ext Polegar` (36) e `Abdução Polegar` (37) rodavam o **conjunto inteiro em torno da
  origem do mundo** (nós `TF_AbducaoPolegar` + `TF_ExtFlexPolegar`), não a junta CMC. Sem
  oposição/pronação real → "falta ângulo".

## Geografia medida (espaço LOCAL da árvore, `Biomodelo_Edu`)

- Carpo (punho) na **origem (0,0,0)**; **+Y = proximal** (antebraço até +269 = Comp Antebraço),
  **−Y = distal** (dedos até −217), **+X = radial** (lado do polegar), Z = espessura (~±16).
- `Carpo_raio = Esp × 1.1 × 0.6249 = 19.53` (Edu); semieixo-Y do carpo = ×0.8 scale = **15.6**.
- Punho: borda radial em **X ≈ +20** local; largura ~44 (≈ Perímetro Punho/π).
- Base atual do polegar: X=+31.1 (ok, borda radial), **Y=−75 (errado, muito distal)**.

## Convenção FK_Cadeia_Dedo (a espelhar)

Crescimento em **−Y** (distal). Multiplicadores confirmados por índice: negPonta ×−1,
negHalf ×−0.5, negLen ×−1. Por junta:

```
JA   = T(0,−PontaMC,0) · Rz(abd·dir)          # raiz na cabeça do MC + abdução (Z)
M0   = JA · Rx(flexProx)                        # junta prox (flexão em X)
cube0= M0 · T(0,−CompProx/2,0)                  # cubo centrado → Matriz Prox
A1   = M0 · T(0,−CompProx,0);  M1 = A1·Rx(flexMed)   # PIP na face distal
cube1= M1 · T(0,−CompMedia/2,0)                 # Matriz Media
A2   = M1 · T(0,−CompMedia,0); M2 = A2·Rx(flexDist)  # DIP
cube2= M2 · T(0,−CompDist/2,0)                  # Matriz Dist
```

## Arquitetura nova: `Polegar_FK_v2`

Mesma convenção, raiz na **CMC perto do punho** + orientação anatômica rica.

```
Base = T(CMCx, CMCy, CMCz) · Rz(ang_palmar) · Ry(oposicao) · Rz(abd_cmc) · Rx(flex_cmc)
cube_MC   = Base · T(0,−CompMC/2,0)          → Mat MC
J_mcp     = Base · T(0,−CompMC,0)
M_prox    = J_mcp · Rx(flex_MCP)
cube_prox = M_prox · T(0,−CompProx/2,0)       → Mat Prox
J_ip      = M_prox · T(0,−CompProx,0)
M_dist    = J_ip · Rx(flex_IP)
cube_dist = M_dist · T(0,−CompDist/2,0)       → Mat Dist
```

**Juntas na face distal** (o que o usuário pediu): cada Rx gira o que vem depois; MCP fica na
ponta distal do metacarpo, IP na ponta da falange proximal.

### Interface do grupo (12 in / 3 out)
IN: CMC X, CMC Y, CMC Z, Ang Palmar, Oposição, Flex CMC, Abd CMC, Comp MC, Flex MCP,
Comp Prox, Flex IP, Comp Dist. OUT: Mat MC, Mat Prox, Mat Dist.

### Sockets na árvore Biomodelo (contrato 63 → 67)
- **Novos:** `Polegar - Ângulo palmar` (Rz base, "pra dentro da palma", default ~27°),
  `Polegar - Oposição` (Ry, pronação/opor aos dedos, default ~10°),
  `Polegar - CMC recuo` (posição Y perto do punho), `Polegar - CMC radial` (posição X).
- **Recabeados (identifiers preservados):** Flex/Ext Polegar (36) → Flex CMC; Abdução Polegar
  (37) → Abd CMC; Flex Falange Prox (38) → Flex MCP; Flex Falange Dist (39) → Flex IP.
- **Comprimentos** 33/40/43 seguem.
- Âncora CMC calculada na árvore: `CMC_X = f(Largura Metacarpo, radial)`,
  `CMC_Y = f(Carpo_raio, recuo)`, `CMC_Z = plano palmar`.

### Removidos
`TF_AbducaoPolegar`, `TF_ExtFlexPolegar` (rotações de conjunto em torno da origem) — os DOFs
agora vivem na CMC. `Join_Polegar_Raw` → `Join_Polegar` direto.

## Execução — CONCLUÍDA (2026-07-05)

1. **`Polegar_FK_v2` construído** (44 nós, 58 links, 0 inválidos) e validado isolado: 5 poses de
   teste (reta, palmar 90°, flex MCP 90°, oposição 90°, mista com 9 DOFs) — **erro 0.0** contra
   previsão analítica numpy.
2. **Religado na `Biomodelo`** (161→157 nós, 0 links inválidos). Backup:
   `Biomodelo_PREPOLEGAR_20260705T003112` (fake_user). Sockets novos Socket_124–127
   (painel `Polegar - CMC`); âncora calculada na árvore: `CMC_X = Largura_Metacarpo×0.28 + radial`,
   `CMC_Y = Carpo_raio×(−0.5) + recuo`. Removidos: `TF_AbducaoPolegar`, `TF_ExtFlexPolegar`,
   feeders e frame `Rotações Polegar`; instância antiga `Polegar_FK` removida.
3. **Verificado por medição na árvore viva** (punho neutro): 3 cubos vs previsão analítica —
   **erro máx 0.43 mm**. Sweeps de robustez: flex MCP 0/40/80° dobra em arco (Z −7.6→−43);
   oposição 0/45° gira o plano (Z −4.7→−16); abd CMC ±20° varre (34,−101)→(89,−73);
   Largura 82→110 desloca ponta +7.8 mm em X exato (Δ×0.28); Esp 28→40 recua CMC −4.0 mm em Y
   exato (via carpo). **Base escala com a mão; sem posição fixa.**
4. `source_template.py` (67 params + painel novo) e `presets/biomodel_sockets_live.json`
   (67 sockets, roles novos `thumb_palmar_angle/opposition/cmc_setback/cmc_radial`) atualizados.

### Gotchas aprendidos
- **Sockets novos ficam 0 no modifier existente** — setar via `set_param` após criar
  (palmar=27, oposição=10 setados no `Biomodelo_Edu`).
- Blender 5.1: `GeometryNodeTransform.mode` virou input socket `Mode` (menu, valor `'Matrix'`).
- Ao medir o polegar na árvore montada, lembrar que **Desvio/Flex do punho giram a mão inteira**
  — comparar contra previsão exige punho neutro (os "10 mm de erro" eram isso, não bug).
- Medir cubos por atributo marcado POR SEGMENTO (Store Named Attribute após cada TF), não por
  blocos de índice pós-join.

### Pendências
- Réplicas (`Biomodelo_Edu.001/.002/.003`) ainda em árvores forkadas — reapontar pro canônico
  e setar Socket_124–127 nos modifiers (GO do usuário: "pode reapontar depois").
- Item A do diagnóstico (desacoplar Espessura: fator dedos + carpo pelo punho) — aguardando GO.
- Calibração visual dos defaults contra o scan — do usuário.
- `.blend` por salvar após o rebuild.
