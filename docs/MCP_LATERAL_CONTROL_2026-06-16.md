# Ajuste lateral (X) dos pivôs MCP por dedo — 2026-06-16

Branch: `codex/biomodel-source-migration`. Árvore viva `Biomodelo`, objeto `Biomodelo_Edu`.

## Pedido

Mesma família de controle que `Dedos - Avanço MCP` (que move o pivô/esfera MCP no eixo
**Y/distal**), mas para o **movimento lateral (X)** das elipses MCP — ajuste fino por dedo de
quão "para dentro/fora" cada cabeça MCP (e o dedo ancorado nela) fica.

## Arquitetura (espelha o Avanço, mas no X)

A posição lateral de cada cabeça MCP já vinha de `MCP_X_Final_<dedo>` = `MCP_Guide_X` (largura da
palma × fator) `+` `MCP_XComp_From_WristDev` (compensação por desvio do punho). Esse valor alimenta
**dois** consumidores ao mesmo tempo:

- `MCP_Pos_<dedo>.X` — posição da esfera MCP;
- `FK_<nó>.Base X` (`j0v.X`) — base/pivô do dedo dentro do grupo FK.

Por alimentar os dois da **mesma fonte**, somar o offset ali move a **articulação no mundo** (esfera
+ base juntas), respeitando o invariante anti-escada da sessão da cinemática MCP. E como X é o
**eixo da rotação de flexão** (`Rx`), o deslocamento lateral é **imune à flexão** por construção
(dz = 0 em qualquer ângulo).

Inserção por dedo (Indicador→`FK_Dedo1`, Médio→`FK_D3`, Anelar→`FK_Dedo2`, Mindinho→`FK_D5`):

```
MCP_Lateral_<dedo>   = ADD(Dedos - Lateral MCP geral, <Dedo> - Lateral MCP)
MCP_X_AjusteLat_<dedo> = ADD(MCP_X_Final_<dedo>, MCP_Lateral_<dedo>)
                         → MCP_Pos_<dedo>.X  e  FK_<nó>.Base X   (religados de X_Final p/ AjusteLat)
```

8 nós novos (4 `MCP_Lateral_*` + 4 `MCP_X_AjusteLat_*`), todos em `Frame_MCP_Anchors_Arco`.
Árvore: 277 nós / 429 links.

## Sockets novos (contrato 58 → 63)

Painel **Dedos - MCP / Pivôs**, logo após o bloco de Avanço, subtype `DISTANCE`, range −40..40,
default **0** (geometria-neutro):

| Nome | Identifier | Role |
|---|---|---|
| `Dedos - Lateral MCP geral` | `Socket_118` | `fingers_lateral_mcp_general` |
| `Indicador - Lateral MCP` | `Socket_119` | `index_lateral_mcp` |
| `Médio - Lateral MCP` | `Socket_120` | `middle_lateral_mcp` |
| `Anelar - Lateral MCP` | `Socket_121` | `ring_lateral_mcp` |
| `Mindinho - Lateral MCP` | `Socket_122` | `pinky_lateral_mcp` |

Convenção de sinal: **positivo = lado radial/polegar (+X)**, negativo = ulnar/mindinho.
`source_template.py` (PARAMETERS 63) e `presets/biomodel_sockets_live.json` (socket_count 63)
atualizados.

## Verificação objetiva

- **Zero-regressão:** com todos os laterais = 0, malha idêntica ao baseline (1746 verts, bbox X
  [−90.87, 96.82]).
- **Isolamento por dedo:** offset num dedo move **exatamente 290 verts** (3 falanges + 1 esfera);
  o geral move **1160 = 4×290** (os 4 dedos juntos).
- **Magnitude exata:** slider −15 → deslocamento rígido `(−14.934, +1.406, 0)`, módulo
  `√(14.934² + 1.406²) = 15.000` mm. A componente Y é a inclinação do desvio do punho (−5.38°): o
  dedo desliza pelo **eixo lateral local da palma** (anatomicamente correto), não pelo X global.
- **`dz = 0.0` exato** e **deslocamento idêntico a 90° de flexão** → zero escada, imune à flexão.
- `min_dx == max_dx` em cada teste → translação rígida (dedo permanece ancorado na sua esfera).

## Gotchas da sessão

1. **`is not` vs `!=` em bpy:** ao religar consumidores, `l.to_node is not aj` deu *True* mesmo
   sendo o mesmo nó (bpy devolve wrappers novos a cada acesso) → o link `X_Final→Ajuste` virou
   **self-loop** `Ajuste→Ajuste` e perdeu a base. Sempre comparar nós por `==`/`.name`, nunca `is`.
2. **Painel com nome bichado (pré-existente):** o painel que de fato contém os sliders MCP se chama
   `Dedos - MCP / Piv?s` (um `?` literal, 0x3f, no lugar do `ô`); existe **também** um painel
   vazio `Dedos - MCP / Pivôs` (ô correto). Os novos sockets entraram no painel certo (o `?`). O
   preset guarda o nome curado (`Pivôs`). Limpeza opcional: renomear o painel e apagar o vazio.
3. **Render do bridge com framing automático saiu em branco** — usei a câmera `_codex_arco_mcp_cam`
   direto via `execute_code` (workbench). Verificação que vale é a numérica acima.

## Pendências

- Salvar o `.blend` / snapshot (Ctrl+Z do usuário já reverteu edições do bridge antes).
- Opcional: limpar o painel duplicado/`?` e, se o usuário quiser, expor `FK_GapEdge`/fatores de arco
  como sliders.
