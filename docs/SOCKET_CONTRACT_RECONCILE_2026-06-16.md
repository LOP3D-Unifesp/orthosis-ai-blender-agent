# Reconciliação do contrato de sockets (2026-06-16)

A árvore viva `Biomodelo` evoluiu muito além do que os arquivos-espelho descreviam. Esta passada
re-extraiu a interface real e sincronizou os artefatos **mecânicos/seguros**, deixando a parte
**semântica (derivação antropométrica)** explicitamente para a calibração (front PARADA).

## Fonte de verdade

**`presets/biomodel_sockets_live.json`** (novo) — extração canônica dos **58 sockets** de entrada
da árvore viva: `identifier`, `name`, `socket_type`, `panel`, `value`. Gerado por
`runtime/inspect/gen_contract.py` a partir de uma extração da interface via bridge. Tudo o mais
deve sincronizar com este arquivo.

## Estado: o que estava defasado

| Arquivo | Antes | Agora |
|---|---|---|
| árvore viva `Biomodelo` | **58 sockets**, 4 dedos individuais, sistema MCP, sem offset/pivôs | (verdade) |
| `source_template.py` PARAMETERS | 31 sockets, **2 cadeias** (Falange 1/2), perímetros | **RECONCILIADO p/ 58** |
| `presets/scan_referencia.json` | 31 params, valores antigos | **REGENERADO p/ 58** (schema 2.0) |
| `anthropometry.py` DERIVED/POSE | mapeia **2 cadeias** (D2/D3 média, D4/D5 média) | **FLAGGED, não alterado** |

## Os 58 sockets, por painel

- **Geral (1):** `Largura Dedo` (80) — largura comum das falanges dos dedos longos.
- **Medidas / tamanho (9):** Comp Antebraço (21), Perímetro Cotovelo (22), Perímetro Punho (23),
  Comp Metacarpo (29), Largura Metacarpo (30), Espessura da Palma (31), Comp Metacarpo Polegar (33),
  Comp Falange Prox/Dist Polegar (40, 43).
- **Movimento / pose (8):** Desvio Rad/Ulnar (24), Flex/Ext Punho (25), Curva Palma 1/2 (27, 28),
  Flex/Ext + Abdução Polegar (36, 37), Flex/Ext Falange Prox/Dist Polegar (38, 39).
- **Dedos - Abduções (5):** geral (99) + Indicador/Médio/Anelar/Mindinho (76, 87, 77, 88).
- **Dedos - Comprimentos (12):** 4 dedos × 3 falanges (50/53/56, 81/82/83, 63/66/69, 84/85/86).
- **Dedos - Movimento (15):** 3 gerais (100/101/102) + 4 dedos × 3 falanges (47–49, 92–94, 60–62, 95–97).
- **Dedos - MCP / Pivôs (8):** Avanço geral (110) + Curvatura arco (111) + 4 avanços por-dedo
  (112–115) + MCP Visual coroa (116) + MCP Raio cabeças (117 — **dead**, o raio real vem de
  `Punho_raio×0.432`).

## Mudanças de nome importantes (mesmos identifiers)

- `Socket_50/53/56` "…Falange 1" → **"Indicador - …"**; `Socket_63/66/69` "…Falange 2" → **"Anelar - …"**.
- `Socket_76/77` "Abdução Dedo 1/2" → **"Indicador/Anelar - Abdução"**.
- Novos (Médio/Mindinho + gerais + MCP): 80, 81–88, 92–97, 99, 100–102, 110–117.
- Removidos no rework MCP: `Socket_104–108` (Offset MCP / pivôs por-dedo).

## Pendência explícita (calibração — PARADA)

`anthropometry.py` ainda deriva o contrato de **2 cadeias**. Reconciliá-lo exige redesenhar a
derivação para **4 dedos individuais** (não mais média D2/D3 e D4/D5), mapear os novos controles
(larguras de dedo, sistema MCP) e atualizar `tests/test_anthropometry.py`. Isso é trabalho da
calibração antropométrica, deliberadamente adiado ("automações antes da calibração"). O módulo
recebeu um aviso de cabeçalho e **não deve ser aplicado** na árvore atual até essa reconciliação,
sob risco da mão deformada (já ocorrido — ver memória do projeto).
