---
title: Cartesian Caramel — Everyday Geometry Node Assets V4
applies_when: proposal,diagnosis,reference_review,orthosis_refactor,clearance,uv
topics: geometry_nodes,assets,sdf,clearance,uv,tangent,curve,extrude,relax
priority: high
lang: pt
status: observed
source_kind: external_blend
---
# Everyday Geometry Node Assets V4

## Fonte e integridade

Arquivo observado:
`C:\Users\Eduardo\Downloads\Geometry Node Assets v4.blend`

- autor/produto: Cartesian Caramel, *Everyday Geometry Node Assets V4*;
- fonte indicada pelo arquivo: download oficial do Gumroad;
- Blender do arquivo inspecionado: 5.2.0 LTS;
- tamanho: 2.169.880 bytes;
- SHA-256:
  `4AB4D9A731694C8A19507358A12DCFE8BC42AF801C94B40A762F443F2514F1C5`;
- 17 node groups no total;
- 15 node groups marcados como assets;
- dumps estruturais somente leitura:
  `runtime/external_analysis_assets_v4/`.

Página oficial:
https://bbbn19.gumroad.com/l/hfcfht

## Licenciamento

A página oficial oferece o arquivo por preço livre e orienta instalá-lo como
Asset Library, mas não apresenta uma licença explícita de redistribuição no
conteúdo público inspecionado.

Consequência:

- é seguro estudar o desenho e testar o arquivo local recebido pelo usuário;
- não copiar ou embarcar os node groups no backend/produto distribuído até
  confirmar por escrito os termos de uso e redistribuição;
- conceitos úteis devem preferencialmente ser reimplementados internamente,
  com nomes, interface, testes e documentação próprios.

Este registro contém apenas análise derivada; nenhum node group foi copiado
para o biomodelo.

## Inventário e prioridade

| Asset | Aplicação possível | Prioridade |
|---|---|---:|
| `SDF Mesh` | campo de distância, normal, ponto mais próximo e offset | alta como referência |
| `UV Tangent` | frame tangente/bitangente/normal sobre a casca | alta |
| `Curve to Mesh UV` | UV para reforços, bordas e tubos gerados por curva | média-alta |
| `Seams from UV` | diagnóstico de orientação e costuras entre patches | média-alta |
| `Relax Points` | distribuir sementes de perfuração | média, exige adaptação |
| `Solid Extrude` | alternativa de espessura com fundo opcional | média, só comparação |
| `Curve Vectors` | vetor até o próximo ponto da spline | média |
| `Set Curve Vectors` | reconstruir pontos de curva por soma de vetores | média |
| `Normal Displace` | preview simples de offset normal | baixa-média |
| `Point Grid 3D` | amostragem volumétrica e depuração | baixa |
| `Circular Array` | repetição radial genérica | baixa |
| `Ease Functions` / `v2` | remapeamento de controles e falloffs | baixa |
| `SDF Collision` | resposta dinâmica com velocidade, bounce e friction | baixa para o produto |
| `Velocity Step` | simulação temporal de partículas | não recomendada no núcleo |

`.BounceOut` é um helper interno. `Geo Node Groups` é apenas a árvore de
apresentação dos assets.

## Análise dos candidatos principais

### 1. `SDF Mesh`

Entradas:

- modo `Points`, `Edges` ou `Faces`;
- geometria alvo;
- raio;
- posição de amostragem.

Saídas:

- distância assinada;
- normal;
- posição mais próxima;
- vetor de offset.

No modo `Faces`, o sinal é calculado pela orientação da normal mais próxima:
o grupo compara o vetor entre a amostra e a superfície com a normal amostrada.
Isso é conceitualmente próximo do `Garantir_Folga` que já existe no V8.

Uso recomendado:

- referência para a API de `ORT_Clearance_Field`;
- saída diagnóstica de distância, normal, posição e correção;
- estatísticas regionais de folga.

Limites:

- o sinal depende de normais consistentes;
- perto de bordas abertas ele não é um teste robusto de interior/exterior;
- não substitui a análise clínica regional;
- é melhor reimplementar nossa versão e expor também `is_valid`, mínimo,
  percentis e número de violações.

`SDF Collision` acrescenta resposta de velocidade, atrito e restituição. Essa
parte é apropriada para simulação visual, não para corrigir silenciosamente uma
órtese determinística.

### 2. `UV Tangent` e `Seams from UV`

`UV Tangent` resolve, por face/corner, um frame:

- tangente U;
- bitangente V;
- normal.

Ele usa posições e diferenças UV de dois cantos vizinhos, resolve o sistema
local e projeta a tangente no plano da face. `Seams from UV` detecta
descontinuidades UV entre os cantos dos dois lados de uma aresta.

Aplicação direta no nosso pipeline:

```text
Patch de Coons
  -> armazenar ort_uv + patch_id antes do Set Position
  -> ORT_SurfaceFrame_Debug
  -> orientação de padrões, slots e reforços
  -> diagnóstico de inversões e costuras
```

Hoje `RENATA_GN_V8_Patch_Coons` lê o `UV Map` da `Mesh Grid` para calcular a
superfície, mas não expõe nem armazena esse UV para consumidores posteriores.
Esse é o melhor insight novo do pacote.

Cuidados:

- cada patch reinicia U/V em 0..1;
- orientações de curvas podem inverter U ou V;
- `patch_id`, `edge_role` e `orientation` precisam acompanhar o UV;
- `Mesh to Volume -> Volume to Mesh` destrói essa parametrização, portanto o
  frame deve ser consumido antes do remesh ou recalculado por outro método.

### 3. `Curve to Mesh UV`

Captura o fator ao longo da curva e do perfil, executa `Curve to Mesh` e devolve
UV por corner. Pode usar fator normalizado ou comprimento real. Também respeita
o atributo de curva `radius` quando presente.

É útil para:

- reforços tubulares ao longo de bordas;
- guias visuais e rails estruturais;
- peças auxiliares derivadas de curvas;
- UV previsível nesses elementos.

Não substitui os patches de Coons: a casca V8 é uma superfície limitada por
quatro curvas, não uma extrusão de perfil ao longo de um caminho.

### 4. `Relax Points`

Executa iterações de repulsão pelo vizinho mais próximo. Pode melhorar a
distribuição de sementes para perfurações, mas move os pontos livremente em 3D.

Para uso na órtese, uma versão própria precisaria:

- reprojetar cada iteração na superfície;
- respeitar bordas e curvas estruturais protegidas;
- usar uma semente determinística;
- manter um `id` estável para auditoria;
- operar antes do remesh quando depender de `ort_uv`/`patch_id`.

Não deve relaxar anchors clínicos nem curvas canônicas.

### 5. `Solid Extrude`

Desloca a superfície inicial por `-Midlevel * Strength`, extruda pela normal e,
opcionalmente, junta uma cópia invertida da superfície inferior.

É uma boa referência para testar espessura centrada ou unilateral. Não deve
substituir imediatamente `RENATA_GN_Voronoi_Borda_Espessura_V8` porque:

- offset por normal pode se auto-intersectar em alta curvatura;
- a solda interna usa distância fixa de `0.001` unidades;
- a unidade e a tolerância precisam ser convertidas para o contrato métrico do
  projeto;
- a cadeia V8 aprovada já possui espessura, bordas e remesh opcionais.

## Relação com anchors e índices

Alguns assets usam `Index`, mas em contextos locais e coerentes:

- `Curve Vectors`: ordem dos pontos dentro da própria spline;
- `UV Tangent`: índices de corners da face que está sendo avaliada;
- `Point Grid 3D` e `Circular Array`: enumeração da geometria gerada.

Isso não justifica usar índice de vértice como identidade de anchor. O padrão
correto continua sendo:

```text
anchor_id / matriz semântica
  -> curvas e superfícies
  -> índices locais descartáveis dentro de cada algoritmo
```

`Set Curve Vectors` é interessante para reconstruir uma spline a partir de
vetores acumulados, mas as matrizes explícitas da arquitetura V4 continuam
mais adequadas para FK e anchors clínicos.

## Próximos experimentos recomendados

1. Expor `ort_uv` e `patch_id` em **um único** patch de Coons isolado.
2. Criar `ORT_SurfaceFrame_Debug_v0` próprio e comparar seu frame com
   `UV Tangent`.
3. Criar `ORT_Clearance_Field_v0` próprio e comparar com `SDF Mesh` e
   `Garantir_Folga`.
4. Testar `Relax Points` somente em sementes de perfuração, com reprojeção e
   máscara de borda.
5. Comparar `Solid Extrude` em uma cópia de um patch, medindo espessura,
   auto-interseção, bordas e escala.

