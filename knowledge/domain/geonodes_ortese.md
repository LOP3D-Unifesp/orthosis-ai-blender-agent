---
title: GN Orthosis System Overview
applies_when: clarification,proposal,diagnosis
topics: orthosis,system,proxy,bezier,anchor,architecture,biomodel,parametric,layers
priority: low
lang: pt
---
# Geo Nodes - Ortese de Membro Superior

## Objetivo do projeto

O objetivo de longo prazo e um sistema parametrico para gerar uma ortese de membro superior a partir de medidas, angulos e regras clinicas, com controle fino dentro do Blender. O agente nao deve so "montar nos"; ele deve ajudar a transformar exploracoes de Geometry Nodes em um software coerente de modelagem parametrica.

## Onde estamos hoje

O projeto ja tem tres blocos reais em andamento:

1. **Biomodelo proxy**
   Um biomodelo reconstruido com primitivas, organizado em regioes anatomicas e regularizado por uma cadeia de remesh em GN.

2. **Curvas da ortese**
   Caminhos e perfis com segmentos Bezier encadeados, incluindo um padrao de continuidade suave entre segmentos.

3. **Primeiros parametros expostos**
   Alguns tamanhos do antebraco e do punho ja aparecem como inputs do grupo, o que mostra que a arvore ja nao e puramente manual.

## O que e um proxy

Neste projeto, um **proxy** e uma representacao simplificada e controlavel da anatomia. Ele nao tenta copiar perfeitamente o scan. Ele tenta preservar as partes que importam para projeto, ajuste e automacao.

No nosso caso, o proxy serve para:

- representar antebraco, punho, palma, polegar e dedos como regioes controlaveis;
- receber parametros clinicos de pose e proporcao;
- ancorar caminhos e perfis da ortese;
- permitir experimentacao sem destruir a referencia original do scan.

## O que e um proxy canonico

Um **proxy canonico** e a versao de referencia do biomodelo proxy que o software passa a tratar como padrao comum entre casos.

Ele nao e um paciente especifico. Ele e o mesmo "molde logico" usado para todos os casos, com os mesmos tipos de blocos, pivots, anchors e familias de parametros.

A ideia e:

- varios scans diferentes sao ajustados para caber nesse mesmo modelo logico;
- o que muda entre os casos sao os parametros;
- esses parametros podem ser comparados, salvos, estudados e depois expostos no painel.

Sem um proxy canonico, cada arvore vira um caso isolado. Com um proxy canonico, varios casos passam a alimentar o mesmo software.

## Estrategia de representacao

O sistema deve ser separado em quatro camadas:

### 1. Shape parameters
Descrevem o corpo base.

Exemplos:
- comprimento do antebraco;
- raio do punho;
- raio do antebraco;
- largura e arco da palma;
- comprimentos relativos de metacarpos e falanges.

### 2. Pose parameters
Descrevem a configuracao clinica.

Exemplos:
- flexao e extensao do punho;
- desvio radial e ulnar;
- flexao de metacarpos;
- flexao de falanges por segmento;
- parametros especificos do polegar.

### 3. Anchor system
Descreve frames e pontos de referencia que organizam tanto o biomodelo quanto a ortese.

Exemplos:
- `forearm_frame`
- `wrist_frame`
- `palm_frame`
- `thumb_frame`
- anchors de inicio, transicao e fim do caminho da ortese
- anchors de perfis

O primeiro conjunto canonico destes anchors esta definido em `knowledge/domain/canonical_anchor_system.md`.

### 4. Orthosis parameters
Descrevem a ortese em si.

Exemplos:
- offsets da casca;
- folgas;
- espessura futura;
- perfil do antebraco;
- caminhos Bezier da ortese;
- transicoes entre perfis.

## Regra importante: biomodelo e curvas devem compartilhar a mesma base

A ortese nao deve depender apenas do scan bruto.

Tambem nao faz sentido fazer o biomodelo depender diretamente de uma curva desenhada ad hoc.

O caminho mais coerente e:

- biomodelo proxy e curvas da ortese lerem o mesmo sistema de anchors e parametros;
- quando o punho muda, o proxy muda;
- quando o proxy muda, os anchors mudam;
- quando os anchors mudam, os caminhos e perfis da ortese acompanham.

Isso preserva alinhamento entre anatomia parametrica e geometria da ortese.

## Fonte de dados do projeto

O software deve conviver com diferentes tipos de referencia:

- scans ruins ou incompletos de maos espasticas;
- scans melhores da mao contralateral;
- orteses ja produzidas a partir desses casos;
- medidas clinicas e observacoes do usuario.

O papel do proxy canonico e justamente absorver essa variacao e converter casos distintos em um mesmo espaco parametrico.

## Como evoluir o sistema

A evolucao mais promissora hoje parece ser:

1. definir um proxy canonico comum;
2. reconstruir diferentes biomodelos dentro desse mesmo esquema;
3. observar quais parametros realmente variam entre os casos;
4. distinguir o que e shape, pose e ortese;
5. promover os parametros maduros para o painel;
6. transformar os patterns mais estaveis em recipes e depois em tools.

## Estado atual consolidado

Hoje ja podemos considerar como conhecimento do projeto:

- existe um biomodelo proxy segmentado por primitivas;
- existe uma cadeia de remesh em GN para regularizar a montagem;
- ja existem curvas Bezier relevantes para o caminho da ortese;
- ja existe um perfil inicial de antebraco;
- ja existe uma necessidade clara de alinhar parametros clinicos e curvas da ortese ao mesmo sistema de referencia.

## Perguntas abertas que continuam validas

- Quais anchors devem ser a fonte principal de verdade do sistema?
- Como separar shape e pose sem engessar a arvore cedo demais?
- Quais parametros clinicos devem aparecer primeiro no painel?
- Em que ponto cada pattern deve virar recipe ou tool?
- Como comparar casos diferentes sem depender de valores arbitrarios de `Transform Geometry`?

## Fora do escopo imediato

- biomecanica validada clinicamente;
- rigging anatomico completo;
- copia fiel do scan;
- interface final para usuario nao tecnico.

O foco agora e construir uma base parametrica forte, legivel e evolutiva.
