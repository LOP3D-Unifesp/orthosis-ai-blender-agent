---
title: G1 Continuity Pattern
applies_when: mutation_request,proposal,diagnosis
topics: g1,continuity,bezier,tangent,smooth,vector_math,pattern,mode2,midpoint,transition
priority: medium
lang: pt
---
# Padrao G1 e Shared Mid Handle para Curvas Bezier

## Papel deste arquivo

Este arquivo registra duas coisas ao mesmo tempo:

1. o **padrao ja validado** na arvore atual para continuidade suave entre dois segmentos Bezier;
2. a **abstracao alvo** que queremos transformar em recipe e possivelmente em botao de insercao no futuro.

## O problema

Uma unica curva Bezier costuma ser curta demais para varias regioes da ortese, especialmente:

- transicao antebraco -> mao;
- curvatura da regiao do punho;
- contornos ao redor do polegar;
- detalhes de perfil na palma e nas falanges.

Quando dois segmentos sao encadeados sem regra clara, surgem:

- kink na tangente;
- loops;
- duplicacao semantica do ponto do meio;
- excesso de handles para o usuario controlar.

## O que ja esta validado hoje

A arvore atual ja usa dois segmentos Bezier encadeados com continuidade suave entre eles. O padrao matematico ja validado e o de **tangente espelhada** na juncao.

Quando o primeiro segmento fornece um handle de saida e o segundo precisa herdar a continuidade, usamos uma cadeia de tres `Vector Math`:

- `Subtract`
- `Scale`
- `Add`

Formula atual:

```text
start_handle_B = ponto_juncao + (-end_handle_A * tensao)
```

Isso funciona muito bem quando:

- o segundo segmento deve sair da juncao com continuidade suave;
- o comportamento ideal e o de tangente refletida;
- queremos uma versao confiavel e simples do acoplamento.

## Tres modos de usar um ponto medio compartilhado

### Modo 1 - shared point only
Os dois segmentos compartilham so o ponto medio.

- `h_left` e `h_right` sao independentes;
- ha continuidade posicional, mas nao necessariamente suavidade.

### Modo 2 - shared controller, asymmetric magnitudes
Esse e o modo mais interessante para o projeto.

- existe um ponto medio unico;
- existe uma direcao tangente conceitual unica;
- os comprimentos do lado esquerdo e direito podem ser diferentes.

Formula:

```text
h_left = p1 - u * L_left
h_right = p1 + u * L_right
```

Onde:
- `p1` = ponto medio compartilhado
- `u` = direcao tangente normalizada
- `L_left` = comprimento do handle esquerdo
- `L_right` = comprimento do handle direito

Esse modo e o melhor candidato para recipe reutilizavel e para futuro botao de insercao.

### Modo 3 - mirrored tangent
Os dois lados do ponto medio sao espelhados.

- e o modo mais proximo do que a arvore atual ja faz;
- excelente para continuidade suave rapida;
- menos flexivel para assimetrias locais.

Formula simplificada:

```text
h_right = p1 + v
h_left = p1 - v
```

## Recomendacao do projeto

### Para a arvore atual
Manter o padrao validado de tangente espelhada quando ele ja estiver funcionando e ajudando a estabilizar a curva.

### Para recipes e templates futuros
Promover o **Modo 2** como padrao reutilizavel.

Por que:
- ele preserva um modelo mental simples;
- reduz o numero de controles independentes;
- permite assimetria local na mao e na ortese;
- se adapta melhor a caminhos e perfis mais complexos.

## Contrato semantico que queremos preservar

Mesmo que o Blender use dois `Bezier Segment`, o sistema deve tratar estes elementos como uma entidade conceitual unica:

- `start_point`
- `start_handle`
- `mid_point`
- `mid_direction`
- `mid_left_length`
- `mid_right_length`
- `end_point`
- `end_handle`

Ou seja: o ponto do meio nao deve existir duas vezes como se fossem duas decisoes separadas.

## Relacao com a ortese

Esse pattern deve ser usado para:

- caminho inferior da ortese;
- transicoes no punho;
- curvas ao redor do polegar;
- detalhes da mao e das falanges;
- repeticao de perfil ao longo de caminhos mais articulados.

## Sinais de que este pattern merece virar setup reutilizavel

No projeto atual, este pattern ja merece status de primeira classe porque:

- ele ja aparece na arvore ativa;
- ele reduz a complexidade de controle;
- ele vai se repetir em mais de uma frente da ortese;
- ele conecta bem conhecimento de dominio, recipe e futura UI.

## O que um recipe ou botao futuro deveria inserir

Um setup inicial deste pattern deveria criar:

- Segmento A
- Segmento B
- controles do ponto medio
- calculo dos handles do meio
- opcao de juntar os dois segmentos
- opcao de debug visual

## Regra pratica para o agente

Quando o usuario quiser "duas Beziers conversando como uma curva so", a resposta ideal nao e improvisar do zero toda vez.

A resposta ideal e reconhecer que isso e um pattern conhecido do projeto e tratá-lo como:

- conhecimento consolidado;
- recipe reutilizavel;
- futuro candidato a template inserivel pela interface.
