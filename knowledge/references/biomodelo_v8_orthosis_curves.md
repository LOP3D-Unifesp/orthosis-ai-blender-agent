---
title: Biomodelo V8 — órtese por curvas e patches de Coons
applies_when: proposal,diagnosis,reference_review,orthosis_refactor
topics: orthosis,curves,coons,anchors,clearance,voronoi,regression
priority: high
lang: pt
status: observed
source_kind: local_blend
---
# Biomodelo V8 — arquitetura observada da órtese

## Escopo e privacidade

Este registro descreve a arquitetura técnica observada em `biomodelov8.blend`.
Ele não contém coordenadas de curvas, medidas ou malhas do paciente. Os dumps
estruturais usados na inspeção permanecem em `runtime/v8_orthosis_analysis/`,
que é ignorado pelo Git.

Data da inspeção: 2026-07-25.  
Blender usado na inspeção: 5.2.0 LTS.

## Resultado principal

A órtese V8 final não é gerada pelos experimentos paramétricos `V4_ORT_*`.
Ela usa uma cadeia independente:

```text
27 curvas manuais
  -> 48 patches de Coons
  -> união, solda e suavização
  -> Voronoi com proteção de borda
  -> espessura
  -> casca final
```

O objeto vivo usa dois modificadores Geometry Nodes:

1. `RENATA_GN_V8_Superficie_Coons`;
2. `RENATA_GN_Voronoi_Borda_Espessura_V8`.

O primeiro grupo instancia:

- 30 patches para antebraço/mão;
- 18 patches para polegar;
- 2 segmentos sintéticos para resolver a transição na região da mão.

Cada patch usa `RENATA_GN_V8_Patch_Coons`, que recebe quatro curvas de
contorno, intervalos de amostragem independentes e resolução U/V.

## Evidências quantitativas

- 48 patches de Coons;
- 27 referências diretas a objetos de curva;
- 384 campos de início/fim dos contornos;
- 266 desses campos possuem valores intermediários, específicos da montagem;
- resolução padrão dos patches: 9 por 9;
- solda padrão entre patches: 0,2 mm;
- espessura padrão: 3,2 mm;
- Voronoi habilitado por padrão;
- remesh volumétrico desabilitado por padrão.

A entrada `Curva estrutural protegida` está sem objeto no modificador
inspecionado. Portanto, a proteção de margem estrutural existe na interface,
mas não participa da peça V8 avaliada.

Os grupos `Garantir_Folga` e `Ortese_Pele_SDF_Embutida` existem no arquivo,
mas não fazem parte da cadeia final da casca V8.

## Baseline de regressão

Foi comparada a geometria avaliada do objeto V8 com o objeto estático
`PRINT_APROVADA`:

- 92.728 vértices em ambos;
- 185.576 arestas em ambos;
- 92.788 faces em ambos;
- mesmos índices de faces;
- diferença máxima entre vértices correspondentes: 0,000187 mm;
- nenhum vértice com diferença maior que 0,001 mm.

Esse objeto aprovado deve ser preservado como baseline. Uma refatoração da
árvore não deve substituir o V8 diretamente: deve gerar uma variante isolada e
ser comparada contra essa referência.

Essa correspondência por vértice é um teste muito forte e conveniente para a
cadeia final V8, porque as duas saídas comparadas já possuem a mesma topologia.
Ela não transforma a numeração de vértices em contrato do biomodelo modular ou
do sistema de anchors.

## Auditoria F10: dependência de índice nas árvores V4

Foi auditado o snapshot do V8 para responder se a mudança da ordem dos `Join`
do biomodelo pode quebrar a órtese paramétrica:

- `V4_ORT_CurvaAncorada_MC`;
- `V4_ORT_CurvaUlnar_Lateral_Comprimento`;
- `V4_ORT_PerfilAncorado_MC`;
- grupo aninhado `Polegar_FK_v2`.

Resultado: **aprovado para o arquivo inspecionado**.

Nesses grupos não existem `Index`, `Sample Index` ou `Named Attribute` usados
para localizar partes do biomodelo. A ancoragem é feita com matrizes,
transformações, rotações e posições de objetos.

Detalhes relevantes:

- o `Object Info` do biomodelo ulnar fornece apenas o socket `Transform`, não a
  geometria da malha;
- o perfil ancorado amostra uma curva ulnar separada por `Factor`;
- essa amostragem depende da ordem das splines se a curva passar a conter mais
  de uma spline, mas não depende da numeração de vértices do biomodelo;
- o único `Input Index` encontrado no arquivo está em
  `RENATA_GN_V8_Segmento_B_Sintetico`, como detalhe interno de construção de
  curva, sem relação com a identidade dos anchors;
- `Garantir_Folga` usa `Sample Nearest Surface` e também é independente da
  ordem de vértices.

Portanto, a organização legível por dedo pode ser mantida. A regra de projeto
passa a ser: anchors são identificados semanticamente por matrizes/IDs em ramo
separado, nunca pelo número de um vértice depois do `Join`.

## V9 observada

A árvore corrigida da V9 tem o mesmo número de nós e links da árvore V8. A
única fonte de objeto diferente é o perfil de punho, trocado por uma curva
corrigida. Isso demonstra que a arquitetura aceita correções locais sem
reescrever o restante da casca.

## Pontos fortes

- O patch de Coons preserva intenção de desenho e controle explícito das
  aberturas, bordas e transições.
- A cadeia é determinística e reproduz exatamente a peça aprovada para o caso
  inspecionado.
- Antebraço/mão e polegar são decompostos em regiões compreensíveis.
- Voronoi, espessura e remesh opcional estão separados da construção da
  superfície.

## Limitações para generalização

- As 27 curvas são objetos específicos do caso.
- A associação curva/patch está gravada em dezenas de nós `Object Info`.
- Os 266 recortes intermediários são parâmetros implícitos, sem identidade
  semântica ou registro por patch.
- A cadeia final não lê os anchors paramétricos dos experimentos `V4_ORT_*`.
- Não existe uma saída quantitativa de folga no resultado final.
- Não existe um manifesto que relacione cada patch às quatro curvas, suas
  orientações e seus intervalos.

O problema de generalização está antes do patch de Coons, na geração e na
identificação das curvas. O núcleo de superfície não precisa ser substituído.

## Integração recomendada

```text
parâmetros clínicos
  -> biomodelo paramétrico
  -> BM_AnchorGraph
  -> curvas canônicas + correções locais do caso
  -> ORT_CurveManifest
  -> patches de Coons existentes
  -> Voronoi e espessura existentes
  -> ORT_Clearance_Field
  -> validação e exportação
```

### `BM_AnchorGraph`

Implementar internamente um grafo estático de anchors, inspirado apenas no
padrão conceitual da referência externa:

- `anchor_id`;
- `parent_id`;
- `role_id`;
- `rest_matrix`;
- `pose_matrix`;
- `locked`.

Esse grafo deve unificar os transforms que hoje aparecem nos grupos
`V4_ORT_*`. Não deve incluir física, wobble ou simulação por frame.

### Curvas canônicas e correções locais

Cada curva deve ser armazenada no frame local de um anchor. Ajustes manuais do
caso devem ser preservados como deslocamentos residuais, e não como novas
coordenadas absolutas sem relação com o biomodelo.

### `ORT_CurveManifest`

Manifesto mínimo por patch:

```text
patch_id
region
inferior_curve_id
superior_curve_id
left_curve_id
right_curve_id
intervals[8]
top_constant
resolution_u
resolution_v
```

O primeiro manifesto pode ser gerado a partir da árvore V8 existente. Depois,
o backend pode recriar as conexões da árvore ou produzir um único objeto de
curvas com atributos como `curve_id`, `patch_id`, `edge_role` e `orientation`.

### `ORT_Clearance_Field`

Criar uma implementação própria que exponha:

- distância assinada;
- normal da superfície anatômica;
- vetor de correção;
- estado válido;
- mínimo, percentis e quantidade de violações.

O campo deve atuar primeiro como diagnóstico. Uma correção automática pode ser
usada em preview, mas não deve alterar silenciosamente a casca final aprovada.

## Verificação preliminar de folga

Uma consulta de vizinho mais próximo entre os vértices da casca V8 e o
biomodelo encontrou pontos praticamente coincidentes e uma pequena quantidade
de amostras do lado negativo da normal mais próxima.

Esse resultado não certifica interseção: a casca possui faces internas e
externas, bordas abertas e regiões de contato intencional, e a classificação
depende da orientação das normais. Ele apenas confirma que falta uma etapa
explícita, regional e auditável de validação de folga.

## Sequência segura de implementação

1. Extrair um manifesto somente leitura da árvore V8.
2. Criar `BM_AnchorGraph_v0` em objeto e node group separados.
3. Reexpressar uma única curva de antebraço no frame de um anchor.
4. Reaplicar o deslocamento residual do caso e medir o erro contra a curva V8.
5. Gerar um único patch de Coons com a curva parametrizada.
6. Adicionar o campo diagnóstico de folga.
7. Só então montar uma variante V10 completa e comparar com o baseline V8.
