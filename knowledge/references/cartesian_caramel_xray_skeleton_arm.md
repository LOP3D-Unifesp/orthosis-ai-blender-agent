---
title: Cartesian Caramel — X-Ray Skeleton Arm
applies_when: proposal,diagnosis,reference_review,pose_visualization
topics: armature,forearm,pronation,supination,raycast,shader,xray,orthosis
priority: medium
lang: pt
status: observed
license_status: public-demo-cc0
---
# X-Ray Skeleton Arm — referência externa

## Proveniência

- **Autor atribuído:** Cartesian Caramel;
- **demo público:** `SHADING X-Ray Skeleton Arm`;
- **página oficial:** https://www.blender.org/download/demo-files/;
- **licença anunciada na página oficial:** CC0;
- **requisito anunciado:** Blender 5.1 ou mais recente;
- **arquivo inspecionado:** `CC Arm Skeleton XRay v2.blend`;
- **tamanho:** 3.633.508 bytes;
- **SHA-256:** `2E72232DB4DA79E7E2B402B76B6BF9C7806FCA9905E428D85D2729F5BA01383B`;
- **versão usada na inspeção:** Blender 5.2.0 LTS;
- **data da inspeção:** 2026-07-25.

O nome do arquivo e a estrutura correspondem ao demo listado publicamente. O
arquivo local não contém um texto de licença nem um checksum publicado para
comparação; portanto, a página oficial deve permanecer registrada junto a
qualquer elemento reutilizado.

## Resultado principal

Este arquivo não contém Geometry Nodes. Ele combina:

1. uma armature convencional;
2. uma malha externa de pele;
3. uma malha separada de ossos;
4. um material Eevee baseado no nó de shader `Raycast`;
5. glare e ajuste de imagem no compositor.

É uma referência de pose e visualização, não uma solução para gerar a
geometria da órtese.

## Inventário do rig

A armature possui 30 ossos, divididos em 26 na coleção `Deform` e 4 na coleção
`Control`.

Elementos relevantes:

- IK do braço com cadeia de dois ossos, alvo `Arm IK` e pole target;
- `L Arm Twist` entre cotovelo e punho;
- ossos separados para rádio e ulna, cada um com alvo IK distal;
- `Wrist`;
- três segmentos para cada dedo;
- acoplamento de segmentos por `Copy Rotation`;
- limites que deixam o eixo principal de flexão livre e bloqueiam os demais;
- `Humerus Corrective` copiando 50% da rotação do úmero.

A ação incluída possui 132 frames, 88 F-curves e 658 keyframes. O canal de
`L Arm Twist` percorre aproximadamente -71° a +79°, funcionando como uma
representação prática de pronação/supinação.

Há uma restrição `Copy Rotation` duplicada no segmento distal `F P U`. Isso
reforça que o rig deve ser tratado como demo artístico, não como definição
clínica canônica.

## Malhas e deformação

### Pele

- 4.333 vértices;
- 4.313 faces;
- uma única componente;
- sem arestas abertas ou não-manifold;
- 24 grupos de vértices;
- modificador Armature com `Preserve Volume` habilitado.

### Ossos

- 3.674 vértices;
- 7.328 faces;
- 20 componentes;
- 43 arestas de borda;
- 92 arestas não-manifold;
- 26 grupos de vértices.

A malha de ossos é suficiente para visualização, mas não deve ser tratada como
anatomia de fabricação, segmentação clínica ou referência imprimível.

## Técnica visual de raio-X

O material `Arm Skin` usa `ShaderNodeRaycast`, introduzido no fluxo do demo para
Blender 5.1 ou mais recente.

Fluxo observado:

```text
Incoming ray invertido
  + ruído direcional
  -> Raycast
  -> Hit Distance
  -> Power
  -> Map Range
  -> mistura entre Principled e Emission
  -> pequena passagem Transparent
```

O limite principal do `Map Range` vai de 0 a 0,2 unidade da cena. Como o arquivo
está em metros, isso equivale a uma faixa visual de até 200 mm.

Essa distância depende do raio de shading e da direção da câmera. Ela não é
folga entre órtese e pele, espessura de fabricação ou distância assinada
adequada para validação geométrica.

O compositor adiciona:

- `Glare` no modo Bloom;
- o asset `Tune Image`, com `Color Boost` 0,5.

O `Tune Image` está ligado a um caminho relativo de uma instalação beta do
Blender 5.1 que não existe na máquina inspecionada. O render funciona na sessão,
mas essa referência externa deve ser localizadas ou substituída antes de usar
o compositor como asset portátil.

## Diferença de unidades

O demo usa `METRIC` com escala 1,0 e dimensões em metros. O Biomodelo Refactor
usa `METRIC`, escala 0,001 e coordenadas em milímetros.

Anexar diretamente objetos do demo ao projeto produziria uma diferença de
escala de aproximadamente 1000 vezes. Qualquer experimento deve converter
unidades explicitamente e nunca depender de escala visual aplicada à mão.

## Comparação com o Biomodelo Refactor

O Biomodelo Refactor já tem controles explícitos para:

- flexão/extensão do punho;
- desvio radial/ulnar;
- pose da mão, dedos e polegar.

Ele ainda não expõe um parâmetro canônico para pronação/supinação do antebraço.
O padrão `L Arm Twist` + rádio/ulna separados mostra uma lacuna real:

```text
forearm_pronation_supination_deg
  -> forearm_twist_frame
  -> radius_distal_anchor
  -> ulna_distal_anchor
  -> wrist_pivot_anchor
  -> mão e curvas da órtese
```

Essa implementação deve continuar analítica e determinística em Geometry
Nodes. Não é necessário adotar a armature ou os pesos do demo como núcleo.

## Comparação com a órtese V8

O arquivo não substitui:

- curvas de contorno;
- patches de Coons;
- Voronoi;
- espessura;
- validação de folga.

Pode contribuir em dois pontos:

1. orientar os anchors do punho e da mão quando houver rotação axial do
   antebraço;
2. oferecer uma visualização transparente para conferir biomodelo, scan,
   anchors e órtese simultaneamente.

As curvas V8 devem continuar sendo geradas em frames anatômicos e alimentar o
núcleo de Coons já aprovado.

## O que aproveitar

### Prioridade alta

- adicionar `forearm_pronation_supination_deg` ao vocabulário clínico;
- criar frames separados para antebraço, rádio distal, ulna distal e punho;
- propagar a torção aos anchors que dirigem as curvas da órtese.

### Prioridade média

- IK apenas como controlador de preview, nunca como fonte clínica de verdade;
- material `VIS_Clinical_XRay_v0` para inspeção visual;
- duas camadas sincronizadas, por exemplo scan/proxy ou biomodelo/órtese.

### Não incorporar no núcleo

- malhas genéricas de pele ou ossos;
- pesos artísticos de Armature;
- animação de demonstração;
- Raycast de shader como métrica de folga;
- ruído e bloom em resultados de validação.

## Experimento recomendado

1. Criar o parâmetro `forearm_pronation_supination_deg` com neutro em 0°.
2. Criar `forearm_twist_frame`, `radius_distal_anchor` e
   `ulna_distal_anchor`.
3. Propagar o frame do punho e uma única curva V8 de teste.
4. Comparar posições e orientações em -60°, 0° e +60°.
5. Só depois criar um material de raio-X separado, exclusivamente visual.

## Artefatos locais

Capturas estruturais e renders permanecem em
`runtime/external_analysis_xray/`, ignorado pelo Git.
