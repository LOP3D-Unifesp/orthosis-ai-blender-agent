# Desacoplamento da Espessura da Palma (2026-07-05)

## Problema

`Espessura da Palma` (Socket_31) tinha dois acoplamentos indesejados (diagnóstico
2026-07-04, traçado via bridge):

1. **Espessura → dedos:** todas as espessuras de falanges (4 dedos, ratios 0.714/0.643/0.571)
   e do polegar derivavam de `Esp` direto — pra palma acompanhar um scan gordo, os dedos
   engordavam junto.
2. **Espessura → posição:** `Comprimento_Carpo = Esp×1.1 → Carpo_raio → AnchorY_MC1/2,
   PontaMC_Base, OssoBaseY` — a âncora longitudinal da mão inteira derivava da espessura;
   engrossar a palma **deslizava a mão em Y** (~8 mm no caso típico).

## Solução aplicada (patch incremental, backup `Biomodelo_PREESPESSURA_20260705T132536`)

1. **Socket novo `Dedos - Fator espessura`** (Socket_128, default 1.0, range 0.3–1.6, painel
   raiz/Geral). Em 4 frames (Dedos—Comum, Polegar—Primitivas, Indicador, Anelar) um nó local
   `EspDedos_<GI> = Esp × Fator` alimenta os 13 ratio-nodes de falanges+polegar
   (ThZ4_Prox/Media/Dist; EspRatio_34/35/42/45/52/55/58/65/68/71).
2. **Palma segue Esp crua:** a palma visível hoje são os grupos `Osso_*` (não os cubos-laje,
   que estão MORTOS — ver achados). `OssoEspessura` foi religado de `ThZ4_Prox` (que agora tem
   fator) para o novo `EspProx_Palma = Esp×0.714` (cru). `MCP_Coroa_Z_TopoPalma` e os cubos
   (mortos) de laje já recebiam Esp cru — intocados. Cabeças MCP (`MCP_Raio_Visual`) seguem o
   fator (pertencem visualmente aos dedos).
3. **Carpo rebaseado no punho:** `Comprimento_Carpo` agora = `Punho_raio × 1.567586`
   (k = Esp_atual×1.1 / Punho_raio no momento do patch → zero-regressão por construção).
   Espessura não move mais nada em Y.

## Verificação (por medição)

- **A/B zero-regressão:** árvore atual (fator=1) vs backup pré-patch, mesmos valores de
  modifier, objeto temp: **máx 1.1e-05 mm** em 1762 verts.
- **Fator 0.7:** dedos_Z 20.29→14.20 (×0.6999), palma-osso 21.31 intacta, ponta Y intacta.
- **Esp 40:** palma-osso 21.31→30.0 (×1.408 = 40/28.41 exato), **ponta Y −217.74 intacta**
  (pré-patch a mão deslizaria ~8 mm).
- **Cenário alvo (réplica gorda):** Esp=40 + fator=0.71 → palma 30.0, dedos 20.29 = idênticos
  ao ref. É o caso de uso: replicar palma grossa sem engordar dedos.

## Achados colaterais

- **Nós mortos na palma:** `Cube_Metacarpo1.001→TF_Metacarpo1.001` e
  `Cube_Falange21.001→TF_Falange21.001` (+ feeders TFVec/SzVec/LargPalma_* e cadeia
  AnchorY_MC1/2→NegAnchor) **não alimentam a saída** — a palma real são os `Osso_*`.
  Candidatos a sweep de limpeza (não removidos nesta sessão).
- **Medição em árvore suja:** falhas de scripts de medição deixaram 8 nós Store órfãos
  encadeados (limpos). Lição: cleanup em `try/finally` e validar `n_nodes` após medir.
- **Unwrap do bridge:** `execute_code` retorna `result` no TOPO da resposta
  (`r["result"]`), não aninhado (`r["result"]["result"]`). Scripts que "retornavam vazio"
  eram unwrap errado.
- Durante a sessão o usuário ajustou o polegar novo ao scan: recuo CMC −41.3, radial +8,
  palmar 23.6 — sinal de que o default da âncora CMC (`Carpo_raio×−0.5`) pode ser recalibrado
  para algo mais distal quando houver mais réplicas.
