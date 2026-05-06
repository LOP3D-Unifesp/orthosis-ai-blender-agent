---
title: Shared Bezier Transition Recipe
applies_when: mutation_request,proposal
topics: bezier,curve,continuity,g1,transition,tangent,midpoint,vector_math,segment,path
priority: high
lang: pt
---
# Recipe: Shared Bezier Transition

## Intent

Criar um fragmento reutilizavel de caminho ou perfil composto por dois segmentos Bezier que se comportam como uma unica curva organizada por um ponto medio compartilhado.

## Quando usar

Use esta recipe quando:

- uma unica Bezier for grossa demais para o detalhe local;
- o caminho precisar de inflexao controlada perto de punho, palma ou polegar;
- o usuario quiser um ponto medio organizando dois arcos adjacentes;
- o projeto precisar repetir esse pattern em perfis e caminhos.

## Inputs minimos

- `start_point`
- `start_handle`
- `mid_point`
- `mid_direction`
- `mid_left_length`
- `mid_right_length`
- `end_point`
- `end_handle`
- `resolution_a`
- `resolution_b`

## Comportamento recomendado

1. Normalizar `mid_direction`.
2. Calcular `mid_handle_left = mid_point - mid_direction * mid_left_length`.
3. Calcular `mid_handle_right = mid_point + mid_direction * mid_right_length`.
4. Criar Segmento A de `start_point` ate `mid_point`.
5. Criar Segmento B de `mid_point` ate `end_point`.
6. Juntar as duas curvas quando um output unico for desejado.

## Modo recomendado

O modo recomendado para o projeto e:

- um ponto medio semantico unico;
- uma direcao tangente unica;
- dois comprimentos independentes.

Isso preserva simplicidade sem matar a assimetria necessaria na mao.

## Outputs esperados

- `curve_a`
- `curve_b`
- `joined_curve`
- opcionalmente, geometria de debug

## Observacao de projeto

Mesmo que a implementacao use dois `Bezier Segment`, esta recipe deve expor o ponto medio como uma entidade semantica unica. O usuario nao deve sentir que esta configurando duas curvas sem relacao.
