---
title: Cartesian Caramel Experimental Geometry Node Rig System
applies_when: proposal,diagnosis,reference_review
topics: geometry-nodes,rig,anchors,deformation,collision,sdf,orthosis,biomodel
priority: low
lang: pt
status: candidate
license_status: unverified
---
# Experimental Geometry Node Rig System — referência externa

## Proveniência

- **Autor atribuído:** Cartesian Caramel (`bbbn19`)
- **Produto:** `(Experimental) Geometry Node Rig System`
- **Página pública:** https://bbbn19.gumroad.com/l/kpmoq
- **Distribuição observada:** gratuita / contribuição opcional
- **Arquivo inspecionado:** `4.3 GN Rig System V2.blend`
- **Tamanho:** 2.587.727 bytes
- **SHA-256:** `75F9891245E616FDCB0CDD71366CADC222371FD27FA9FE58B8049FD8064029C2`
- **Versão indicada pelo arquivo:** Blender 4.3
- **Versão usada na inspeção:** Blender 5.2.0 LTS
- **Data da inspeção:** 2026-07-25

O arquivo foi associado ao produto pela URL de download Gumroad preservada no
`Zone.Identifier` do Windows e por uma listagem pública que aponta o produto do
autor.

## Regra de uso

**Não anexar nem copiar os node groups deste arquivo para o biomodelo, para a
órtese ou para o repositório enquanto a licença de reutilização e redistribuição
não estiver explícita.**

Preço zero não equivale automaticamente a licença aberta. A análise abaixo
registra ideias e padrões técnicos, não o grafo externo.

## Inventário observado

O arquivo contém 10 árvores Geometry Nodes:

- `GN Rig Phyisics` — orquestra rig, simulação e colisão;
- `GN Rig Deform` — deforma uma malha por influência de segmentos;
- `B Rig Setup` — deriva hierarquia e matrizes do grafo de ossos;
- `B Update Transforms` — propaga transforms com repetição e limite angular;
- `B Tail Physics` — integra posição e velocidade;
- `B Tail Collision` — corrige colisão das pontas;
- `B Roll` — controla roll por atributo;
- `Distance to Edge` — distância de um ponto a um segmento;
- `Limit Vector Angle` — limita um vetor dentro de um cone angular;
- `Mesh SDF` — aproxima distância assinada, normal e offset de colisão.

Estrutura principal:

1. uma malha sem faces, com 24 vértices e 23 arestas, representa o rig;
2. grupos de vértices `Root`, `Roll` e `Freeze` fornecem controles;
3. `B Rig Setup` grava atributos como `ParentID`, `ChainID`, `TransRest`,
   `TransLocal` e `TransGlobal`;
4. uma zona de simulação atualiza `TailPos` e `TailVel`;
5. uma zona de repetição propaga transforms ao longo da hierarquia;
6. `GN Rig Deform` calcula pesos pela distância do vértice da malha a cada
   segmento do rig e combina offsets `TransRest → TransGlobal`.

Não foram encontrados textos, licença embutida, bibliotecas vinculadas ou
node groups marcados como assets. Há um bake de simulação empacotado.

## Comparação com o biomodelo

O `Biomodelo_v2` é um gerador anatômico paramétrico e determinístico. Ele usa
subgrupos por região, inputs clínicos e cadeias FK explícitas. O arquivo externo
é um rig genérico dirigido por um grafo de pontos e atributos.

O rig externo **não substitui** nossa cinemática. O padrão promissor é usar uma
malha-grafo separada para tornar reais os anchors canônicos:

- vértices = anchors;
- arestas = relação pai-filho;
- `anchor_id`, `parent_id` e `chain_id` = identidade/hierarquia;
- `rest_matrix` e `pose_matrix` = frames canônicos;
- `locked` e `role_id` = semântica operacional.

Para o nosso caso, a hierarquia é conhecida. Portanto, `parent_id` deve ser
armazenado explicitamente; não precisamos inferi-lo com `Shortest Edge Paths`.

Um segundo uso possível é um deformador apenas de **preview/retarget** para
fazer um scan decimado acompanhar a pose do proxy. Ele não deve virar a fonte
da anatomia nem substituir os parâmetros clínicos.

## Comparação com a órtese

Já temos mecanismos mais adequados à fabricação:

- `Garantir_Folga` usa amostragem de superfície para impor distância;
- `Ortese_Pele_SDF_Embutida` usa grids SDF para formar uma pele/casca;
- `V4_ORT_*` ancora curvas e perfis nos parâmetros do biomodelo.

Uma inspeção posterior do `biomodelov8.blend` mostrou que esses mecanismos
existem como experimentos paralelos, mas não compõem a casca V8 final. A cadeia
aprovada usa 27 curvas manuais, 48 patches de Coons e um segundo modificador
para Voronoi e espessura. Portanto, o principal uso do padrão de rig externo é
alimentar as curvas de contorno com anchors estáticos; ele não deve substituir
os patches de Coons.

O `Mesh SDF` externo é útil como referência de **API diagnóstica** porque expõe
normal, distância, offset de correção e validade. Ele não é superior à nossa
cadeia volumétrica para gerar a casca final.

Padrão candidato para implementação própria:

```text
ORT_Clearance_Field
  entrada: geometria alvo, posição de amostra, folga
  saída: distância assinada, normal, correção, válido
```

Isso pode complementar `Garantir_Folga` e permitir validações quantitativas sem
usar uma simulação dinâmica.

## O que aproveitar

### Prioridade alta

1. **Anchor graph estático:** representação concreta dos anchors canônicos com
   matrizes por ponto.
2. **Saídas diagnósticas de folga:** distância, normal, correção e validade.

### Prioridade média

3. **Distância a segmento:** base para pesos de retarget de um scan decimado.
4. **Limite vetorial angular:** útil quando uma orientação vier de alvo/vetor,
   não quando já vem de um ângulo clínico explícito.

### Não incorporar no núcleo

- wobble, gravidade e física por frame;
- colisão dinâmica como gerador da órtese;
- pesos automáticos no shell final;
- cópia integral dos grupos externos.

Esses mecanismos introduzem estado, bake e dependência temporal. O biomodelo e
a órtese de fabricação precisam continuar determinísticos e reproduzíveis.

## Experimentos recomendados

1. Criar `BM_AnchorGraph_v0` em árvore e objeto separados, sem alterar
   `Biomodelo_v2`.
2. Representar primeiro `forearm_origin`, `wrist_pivot`, `palm_center` e
   `thumb_root`.
3. Comparar as matrizes do grafo com as matrizes analíticas atuais em várias
   poses; tolerância-alvo inicial: erro posicional menor que 0,1 mm.
4. Criar `ORT_Clearance_Field_v0` a partir dos nossos próprios grupos e validar
   contra `Garantir_Folga`.
5. Só depois testar um `BM_ScanRetarget_Preview_v0` em scan decimado.

## Artefatos locais da inspeção

Os dumps estruturais completos permanecem em
`runtime/external_analysis/`, que é ignorado pelo Git. Eles contêm a captura
da cena, interfaces, nós, links, atributos e propriedades técnicas necessárias
para continuar a avaliação local sem versionar o grafo externo.
