---
title: Current Tree Anchor Mapping
applies_when: diagnosis,mutation_request,clarification,proposal
topics: anchor,mapping,wrist,palm,orthosis,path,forearm,pivot,semantic
priority: medium
lang: pt
---
# Mapeamento dos Anchors na Arvore Atual

## O que este arquivo faz

Este arquivo existe para responder uma pergunta pratica:

**"Onde os anchors canonicos aparecem na minha arvore de hoje e o que eles mudariam na cena do Blender?"**

A resposta curta e:

- hoje, eles quase nao mudam a cena visualmente;
- neste momento, eles mudam principalmente a forma como pensamos e organizamos a arvore;
- no proximo estagio, eles viram inputs, vetores, pivots e pontos nomeados dentro do GN;
- so depois disso passam a mudar a cena diretamente.

## Regra importante

Nesta rodada, os anchors ainda sao principalmente uma **camada semantica**. Eles ainda nao substituirao automaticamente seus `Transform Geometry` no Blender.

O que eles fazem agora e preparar a arvore para uma migracao organizada:

- de valores soltos
- para pontos de referencia nomeados
- que biomodelo e ortese compartilham

## Como isso impacta sua cena hoje

### O que muda agora
- o projeto passa a ter uma linguagem melhor para discutir a arvore;
- o agente passa a poder raciocinar em termos de `wrist_pivot_anchor`, `orthosis_path_mid_anchor`, etc.;
- fica mais facil decidir quais partes devem virar parametros reais.

### O que ainda nao muda agora
- nao aparece geometria nova automaticamente;
- os nos atuais nao sao substituidos ainda;
- a cena nao se reorganiza sozinha.

## Lote 1 de anchors prioritarios na arvore atual

Os cinco primeiros anchors escolhidos para a sua arvore sao:

1. `wrist_pivot_anchor`
2. `palm_center_anchor`
3. `orthosis_path_start_anchor`
4. `orthosis_path_mid_anchor`
5. `forearm_profile_anchor`

Abaixo esta o que cada um significa na pratica.

---

## 1. `wrist_pivot_anchor`

### Significado
E o ponto funcional onde a mao gira em relacao ao antebraco.

### Onde ele aparece semanticamente hoje
Na sua arvore atual, esse anchor esta distribuido entre:
- a regiao do punho no biomodelo proxy;
- a transicao entre antebraco e mao no caminho da ortese;
- o ponto em que movimentos globais do punho deveriam propagar para a mao.

### Impacto futuro na cena
Quando implementado, esse anchor deve:
- virar o pivot principal para flexao/extensao do punho;
- virar o pivot principal para desvio radial/ulnar;
- orientar tanto biomodelo quanto curvas da ortese.

### Beneficio pratico
Em vez de girar varias partes tentando acertar o punho, voce move uma referencia central.

---

## 2. `palm_center_anchor`

### Significado
E o centro estrutural da palma no proxy.

### Onde ele aparece semanticamente hoje
Na regiao da `Palma` e nas transicoes que conectam polegar, metacarpos e grupos da mao.

### Impacto futuro na cena
Quando implementado, esse anchor deve:
- organizar o arco da palma;
- servir de referencia para abrir lado radial e ulnar;
- ajudar a orientar parte da borda da ortese na mao.

### Beneficio pratico
A palma deixa de ser posicionada so por offsets manuais e passa a ter um centro semantico reutilizavel.

---

## 3. `orthosis_path_start_anchor`

### Significado
E o ponto inicial do caminho principal da ortese.

### Onde ele aparece semanticamente hoje
No inicio do `Caminho Geral`, ou seja, na primeira Bezier principal do percurso da ortese.

### Impacto futuro na cena
Quando implementado, esse anchor deve:
- definir com clareza onde a curva principal nasce;
- alinhar esse inicio com o antebraco e com o primeiro perfil;
- permitir reposicionar o inicio do caminho sem depender de varios ajustes espalhados.

### Beneficio pratico
O inicio da ortese passa a ser um ponto nomeado, nao um monte de valores escondidos em handles e transforms.

---

## 4. `orthosis_path_mid_anchor`

### Significado
E o ponto medio compartilhado entre os dois segmentos principais da curva.

### Onde ele aparece semanticamente hoje
Na juncao entre:
- `Bezier Segment` / `Caminho Geral`
- `Bezier Segment Hand`

Este e exatamente o ponto onde o pattern das duas Beziers "conversando" faz mais sentido.

### Impacto futuro na cena
Quando implementado, esse anchor deve:
- controlar a transicao entre antebraco e mao;
- permitir continuidade mais clara entre segmentos;
- servir como base para o modo 2 do shared mid handle.

### Beneficio pratico
O ponto do meio deixa de existir apenas como combinacao implicita de handles e passa a ser um controle de primeira classe.

---

## 5. `forearm_profile_anchor`

### Significado
E o ponto/frame onde o primeiro perfil da ortese se ancora ao caminho.

### Onde ele aparece semanticamente hoje
Na relacao entre:
- `Sample Curve`
- `Transform Geometry.001`
- primeiro perfil do antebraco

### Impacto futuro na cena
Quando implementado, esse anchor deve:
- alinhar o perfil do antebraco ao inicio do caminho;
- reduzir dependencia de offsets corretivos arbitrarios;
- permitir que o perfil acompanhe o path de modo mais estavel.

### Beneficio pratico
O perfil deixa de ser so uma curva "jogada perto do caminho" e passa a nascer de uma relacao estrutural clara.

---

## O que vamos fazer depois com esses anchors

### Fase A - semantica
Dar nome e funcao a cada anchor.

### Fase B - representacao no GN
Transformar anchors em elementos reais da arvore, por exemplo:
- group inputs vetoriais;
- vetores calculados;
- nos nomeados de referencia;
- pequenos subgrupos de frame/pivot.

### Fase C - migracao da logica
Fazer curvas e primitivas lerem esses anchors.

### Fase D - painel
Expor parametros clinicos e geometricos que passam a alimentar esses anchors.

## Resposta direta a duvida principal

Se voce esta pensando:

**"Entao isso ja mudou minha cena no Blender?"**

A resposta honesta e:
- **ainda nao muito visualmente**;
- **mas mudou bastante a arquitetura conceitual da arvore**;
- e isso e justamente o passo necessario antes de comecarmos a trocar valores soltos por controles parametricos reais.

## Sinal de que estamos no caminho certo

Vamos saber que esse sistema comecou a se tornar real quando conseguirmos dizer coisas como:

- "o punho gira a partir do `wrist_pivot_anchor`"
- "o perfil inicial nasce do `forearm_profile_anchor`"
- "a transicao das duas Beziers e controlada por `orthosis_path_mid_anchor`"

A partir desse ponto, a arvore para de ser um arranjo exploratorio de nos e comeca a virar uma base de software parametrico.
