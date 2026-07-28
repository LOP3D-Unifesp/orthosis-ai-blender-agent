---
title: Canonical Anchor System
applies_when: diagnosis,mutation_request,proposal,clarification
topics: anchor,frame,pivot,reference,bezier,profile,ortese,biomodel
priority: medium
lang: pt
---
# Sistema Canonico de Anchors

## Objetivo

Este arquivo define o primeiro conjunto de anchors canonicos do projeto. Eles servem como pontos e frames de referencia compartilhados entre:

- biomodelo proxy;
- parametros clinicos;
- caminhos Bezier da ortese;
- perfis da ortese.

Sem anchors canonicos, a arvore depende demais de valores locais de `Transform Geometry`. Com anchors canonicos, os controles passam a ter semantica reutilizavel.

## Regra geral

Um anchor pode ser:

- um **point anchor**: posicao de referencia;
- um **frame anchor**: origem + orientacao local;
- um **pivot anchor**: ponto em torno do qual uma parte gira;
- um **derived anchor**: calculado a partir de outros anchors e parametros.

## Invariante de identidade e topologia

Um anchor canônico **não pode ser identificado por índice de vértice** da malha
do biomodelo ou da órtese.

São identidades válidas:

- um nome ou `anchor_id` semântico e estável;
- um socket de matriz explicitamente nomeado;
- um ponto em um `BM_AnchorGraph` separado, com `anchor_id`, `parent_id` e
  `role_id`;
- uma posição ou matriz derivada de outros anchors e parâmetros clínicos.

Não são identidades válidas:

- "vértice 137";
- a posição ocupada por uma entrada em `Join Geometry`;
- a numeração produzida por `Realize Instances`, `Merge by Distance` ou remesh;
- um atributo que se espera sobreviver a `Mesh to Volume -> Volume to Mesh`.

Índices ainda podem ser usados **localmente** dentro de um algoritmo controlado,
por exemplo para percorrer os pontos de uma spline. Nesse caso, o índice
representa a ordem interna daquela curva e não pode virar uma referência
persistida ou uma API entre biomodelo, órtese e backend.

### Consequência para a ordem dos `Join`

Se nenhum consumidor explicitamente versionado usa índices, a ordem das
entradas de `Join Geometry` é livre. A árvore pode agrupar a geometria por dedo,
por tipo ou por legibilidade sem alterar o contrato dos anchors.

Por isso, a arquitetura modular "um grupo por dedo" é compatível com este
sistema. Não é necessário reproduzir a numeração da árvore viva antiga.

### Ramo separado de anchors

O fluxo recomendado é:

```text
parâmetros clínicos
  -> BM_AnchorGraph / matrizes canônicas
       -> biomodelo modular
       -> curvas e perfis da órtese

geometria da órtese
  -> Join / solda / Mesh to Volume / Volume to Mesh
  -> casca final
```

O `BM_AnchorGraph` deve ser produzido antes das operações destrutivas de
topologia e continuar disponível em um ramo separado. Ele não deve ser
extraído novamente da pele remesheada.

### Critério de regressão

Uma refatoração do biomodelo deve comparar:

- matrizes e posições dos anchors canônicos;
- medidas clínicas e comprimentos relevantes;
- forma avaliada, limites e volumes;
- distâncias para superfícies de referência;
- saída final da órtese.

Igualdade de numeração de vértices só é um teste auxiliar quando duas saídas já
possuem deliberadamente a mesma topologia. Ela não é um requisito arquitetural.

## Conjunto inicial recomendado

### 1. `forearm_origin_anchor`
**Tipo:** point/frame anchor  
**Papel:** origem proximal do biomodelo e do sistema do antebraco.

Uso:
- iniciar medidas longitudinais;
- orientar o eixo principal do antebraco;
- servir como origem de comparacao entre casos.

### 2. `wrist_pivot_anchor`
**Tipo:** pivot/frame anchor  
**Papel:** juncao funcional entre antebraco e mao.

Uso:
- flexao/extensao do punho;
- desvio radial/ulnar;
- ponto central de propagacao para mao e ortese.

Observacao:
- este deve ser mais importante que offsets locais do cone ou da esfera do punho;
- biomodelo e curvas devem responder a ele.

### 3. `palm_center_anchor`
**Tipo:** point/frame anchor  
**Papel:** centro estrutural da palma no proxy.

Uso:
- distribuir metacarpos;
- controlar arco da palma;
- orientar parte da borda da ortese sobre a mao.

### 4. `thumb_root_anchor`
**Tipo:** point/pivot anchor  
**Papel:** base do polegar.

Uso:
- abrir, fechar e orientar cadeia do polegar;
- orientar abertura da ortese na regiao do polegar.

### 5. `hand_radial_group_anchor`
**Tipo:** frame anchor  
**Papel:** origem do grupo radial da mao.

Uso:
- metacarpos/falanges do lado radial;
- arco radial da palma;
- relacao com a borda radial da ortese.

### 6. `hand_ulnar_group_anchor`
**Tipo:** frame anchor  
**Papel:** origem do grupo ulnar da mao.

Uso:
- metacarpos/falanges do lado ulnar;
- arco ulnar da palma;
- relacao com a borda ulnar da ortese.

### 7. `orthosis_path_start_anchor`
**Tipo:** point/frame anchor  
**Papel:** inicio do caminho principal da ortese.

Uso:
- ancorar a primeira Bezier do caminho;
- sincronizar o inicio da ortese com antebraco e perfil inicial.

### 8. `orthosis_path_mid_anchor`
**Tipo:** point anchor  
**Papel:** ponto medio compartilhado entre os dois segmentos principais da curva.

Uso:
- juncao entre segmentos Bezier;
- continuidade local;
- transicao entre antebraco e mao.

Observacao:
- semanticamente, este e o ponto do meio da curva, mesmo que existam dois nos Bezier.

### 9. `orthosis_path_end_anchor`
**Tipo:** point/frame anchor  
**Papel:** destino distal do caminho principal da ortese.

Uso:
- finalizar o caminho principal;
- servir de base para bifurcacoes futuras ou caminhos secundarios.

### 10. `forearm_profile_anchor`
**Tipo:** frame anchor  
**Papel:** ponto/frame onde o primeiro perfil da ortese se ancora ao caminho.

Uso:
- alinhar o perfil inicial do antebraco;
- reduzir dependencia de offsets manuais;
- ligar medidas do antebraco ao caminho da ortese.

### 11. `thumb_opening_anchor`
**Tipo:** derived anchor  
**Papel:** orientar a abertura ou contorno da ortese na regiao do polegar.

Uso:
- adaptar path/profiles perto do polegar;
- conectar biomodelo do polegar ao desenho da ortese.

## Relacoes importantes

### Biomodelo
O biomodelo proxy deve se organizar principalmente a partir de:
- `forearm_origin_anchor`
- `wrist_pivot_anchor`
- `palm_center_anchor`
- `thumb_root_anchor`
- `hand_radial_group_anchor`
- `hand_ulnar_group_anchor`

### Caminhos da ortese
Os caminhos principais devem se organizar principalmente a partir de:
- `orthosis_path_start_anchor`
- `orthosis_path_mid_anchor`
- `orthosis_path_end_anchor`
- `thumb_opening_anchor`

### Perfis da ortese
Os perfis devem se organizar principalmente a partir de:
- `forearm_profile_anchor`
- anchors locais derivados ao longo do caminho

## Regra de ouro

Nem o biomodelo deve ser refem das curvas, nem as curvas devem ser refens das primitivas. Ambos devem ler o mesmo sistema de anchors.

## Como adaptar isso para a arvore atual

Na arvore atual, o primeiro mapeamento pratico pode ser:

- cone do antebraco -> shape guiado por `forearm_origin_anchor` e `wrist_pivot_anchor`
- bloco/regiao da palma -> guiado por `palm_center_anchor`
- cadeia do polegar -> guiada por `thumb_root_anchor`
- grupos radial e ulnar -> guiados por `hand_radial_group_anchor` e `hand_ulnar_group_anchor`
- duas Beziers principais -> guiadas por `orthosis_path_start_anchor`, `orthosis_path_mid_anchor`, `orthosis_path_end_anchor`
- primeiro perfil -> guiado por `forearm_profile_anchor`

## Ordem de implementacao recomendada

### Lote 1
Implementar semanticamente:
- `wrist_pivot_anchor`
- `palm_center_anchor`
- `orthosis_path_start_anchor`
- `orthosis_path_mid_anchor`
- `forearm_profile_anchor`

### Lote 2
Adicionar:
- `thumb_root_anchor`
- `hand_radial_group_anchor`
- `hand_ulnar_group_anchor`
- `thumb_opening_anchor`

### Lote 3
Expandir para anchors por dedo e por segmento, se o projeto pedir.

## Sinal de maturidade

Um trecho da arvore comecou a amadurecer quando o agente ou o usuario conseguem dizer:

- "mexa o wrist_pivot_anchor"
- "alinhe o forearm_profile_anchor ao inicio do path"
- "recalcule o orthosis_path_mid_anchor"

em vez de:

- "muda o Transform Geometry.004"
- "ajusta aquele offset ali"

Esse e o tipo de linguagem que aproxima a arvore de um software parametrico real.
