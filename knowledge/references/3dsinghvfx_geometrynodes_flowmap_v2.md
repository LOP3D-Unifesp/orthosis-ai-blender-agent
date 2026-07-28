---
title: 3D Singh VFX — Geometry Nodes Flowmap V2
applies_when: proposal,diagnosis,reference_review,orthosis_pattern
topics: geometry-nodes,flowmap,streamlines,curves,surface,coons,orthosis
priority: medium
lang: pt
status: candidate
license_status: restricted-or-unverified
---
# Geometry Nodes Flowmap V2 — referência externa

## Proveniência

- **Autor provável:** Kuldeep Singh / 3D Singh VFX;
- **produto relacionado:** `Procedural Flowmap`;
- **página pública:** https://3dsinghvfx.gumroad.com/l/procedural-flowmap;
- **arquivo inspecionado:** `Geometrynodes Flowmap V2.blend`;
- **tamanho:** 1.574.256 bytes;
- **SHA-256:** `9DBFDBC56CBA0D9AE7F4980671FBA0023E85E078260C38D006FCDEBFB3F46229`;
- **versão usada na inspeção:** Blender 5.2.0 LTS;
- **data da inspeção:** 2026-07-25.

O nome, a finalidade e a estrutura são compatíveis com os materiais públicos de
3D Singh VFX sobre flowmaps procedurais. O arquivo não contém texto de licença.
A página atual do produto permite uso em projetos, mas proíbe redistribuir o
node group. Portanto, não copiar os grupos para o repositório ou para um
`.blend` distribuível. Registrar apenas ideias, interfaces e resultados
derivados.

## Resultado principal

O arquivo cria linhas de fluxo decorativas a partir de um campo de ruído. Não é
uma simulação de fluido, um solver de tensão nem um cálculo biomecânico.

Há cinco grupos Geometry Nodes:

- `Points`;
- `Curve Flow`;
- `Object Curve Flow`;
- `Flow Loop`;
- `Mesh Curve`.

## Algoritmo observado

```text
pontos iniciais
  -> pontos convertidos em vértices
  -> quatro passos de extrusão
  -> deslocamento pelo campo de ruído
  -> reprojeção opcional na superfície
  -> arestas convertidas em curvas
  -> curvas Bézier com handles automáticos
  -> perfil, raio, material e atributos
```

### `Points`

Gera uma linha de pontos e atribui posições vetoriais aleatórias entre limites
mínimo e máximo. Nos dois planos de demonstração são usados 4.000 e 1.000
pontos.

### `Flow Loop`

É um grupo de cinco nós:

1. extruda apenas os vértices selecionados;
2. seleciona os novos vértices `Top`;
3. move esses vértices para a posição calculada;
4. devolve geometria e seleção `Top`.

`Curve Flow` e `Object Curve Flow` encadeiam quatro instâncias desse grupo. A
trajetória real possui cinco posições principais: a semente e quatro passos.
O input chamado `Subdivide` altera a resolução da curva depois da conversão,
não a quantidade de passos de integração.

### `Curve Flow`

Versão plana:

- lê a posição atual;
- amostra Noise Texture 2D;
- centraliza a cor do ruído subtraindo 0,5;
- multiplica por `Noise Influence`;
- soma o vetor à posição atual;
- repete o processo quatro vezes;
- converte as arestas resultantes em Béziers.

O componente Z da influência é praticamente nulo nos exemplos planos.

### `Object Curve Flow`

Versão sobre superfície:

- distribui sementes nas faces;
- calcula o mesmo deslocamento por ruído 3D;
- consulta a posição mais próxima na geometria original;
- mistura a posição projetada com a posição provisória;
- repete quatro vezes.

O fator de mistura observado é 0,3. A trajetória não é projetada integralmente
na superfície. Não há limite de distância, detecção de salto entre regiões,
tratamento de bordas nem verificação de validade.

### `Mesh Curve`

Converte as curvas em fitas estreitas e captura:

- `UV`: comprimento ao longo da curva + coordenada transversal;
- `R`: valor aleatório por curva;
- `G`: gradiente ao longo da curva.

Os modificadores gravam esses resultados como atributos `UV`, `R` e `G`. Os
materiais usam os atributos para cor, máscara, variação e animação.

## Animação

A geometria é estática. O movimento observado no render vem de drivers nos
materiais:

- `frame / 100`;
- `frame / 50`;
- `frame / 24`;
- `frame`.

Esses valores deslocam coordenadas e máscaras do shader. Não existe advecção
temporal da geometria nem histórico de simulação.

## Custo observado

No frame inspecionado:

- esfera com flowmap: 451.044 vértices e 283.008 faces;
- plano principal: 156.000 vértices e 96.000 faces;
- plano secundário: 51.000 vértices e 32.000 faces.

Esse custo é alto para ser somado diretamente à órtese V8, que já possui cerca
de 92 mil vértices. Linhas de diagnóstico devem permanecer como curvas e usar
densidade bem menor; a conversão para malha deve ser opcional.

## Diferença de unidades

O arquivo usa metros com escala de cena 1,0. O Biomodelo Refactor e a órtese
usam milímetros com escala 0,001. Influências e perfis não podem ser copiados
numericamente: exigem conversão explícita de aproximadamente 1000 vezes.

## Aplicação ao V8

### Prioridade alta: orientação dos patches

Os 48 patches de Coons já possuem direções naturais U/V. Em vez de criar um
campo arbitrário de ruído, devemos preservar essas derivadas como atributos:

```text
patch_id
region_id
patch_u_tangent
patch_v_tangent
```

Linhas de fluxo sobre esses campos podem revelar:

- patches invertidos;
- mudanças bruscas de orientação;
- costuras com tangentes incompatíveis;
- regiões onde os trims manuais mudam a direção esperada.

Nome candidato: `ORT_PatchOrientation_Debug_v0`.

### Prioridade média: padrões orientados

Depois de validar a continuidade, um campo tangente pode orientar:

- rasgos alongados de ventilação;
- nervuras locais;
- linhas estruturais protegidas;
- padrões visuais por região.

Isso deve ser uma alternativa experimental ao Voronoi, não uma substituição
imediata da peça aprovada.

### Prioridade média: contrato GN → material

O padrão de expor `UV`, aleatório por curva e gradiente é útil para visualização
diagnóstica. Uma implementação própria poderia publicar:

- `ort_path_u`;
- `ort_path_v`;
- `ort_region_id`;
- `ort_clearance_mm`;
- `ort_violation`.

O material exibiria direção, região e violações sem alterar a geometria.

## Implementação própria recomendada

```text
semente
  -> campo de direção anatômico
  -> projeção no plano tangente
  -> passo limitado em milímetros
  -> Repeat Zone
  -> projeção validada na superfície
  -> parada em borda, distância excessiva ou região inválida
```

O vetor tangente deve ser:

```text
v_tangent = v - dot(v, normal) * normal
```

Depois deve ser normalizado e multiplicado por um passo explícito em
milímetros. O campo pode vir dos eixos U/V dos patches, dos anchors anatômicos
ou de dados externos validados. Ruído pode ser um detalhe opcional, nunca a
fonte principal de direção clínica.

## Não incorporar no núcleo

- grupos externos originais;
- ruído como direção estrutural;
- quatro passos hard-coded;
- `Geometry Proximity` sem limiar ou validação;
- animação de shader como evidência de fluxo físico;
- densidades de milhares de fitas no objeto final;
- uso como mapa de pressão ou tensão sem dados de solver.

## Experimento recomendado

1. Preservar `patch_id` e tangentes U/V em um único patch V8.
2. Gerar 10 a 20 linhas de diagnóstico sobre esse patch.
3. Cruzar uma costura com o patch vizinho e medir mudança angular.
4. Marcar em vermelho diferenças acima de um limiar.
5. Só depois testar rasgos ou nervuras orientadas em uma variante isolada.

## Artefatos locais

Capturas estruturais e render permanecem em
`runtime/external_analysis_flowmap/`, ignorado pelo Git.

