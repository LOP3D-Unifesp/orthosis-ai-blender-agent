---
title: Forearm Profile Anchor Recipe
applies_when: mutation_request,proposal
topics: forearm,profile,anchor,orthosis,wrist,sample_curve,transform,path,profile
priority: high
lang: pt
---
# Recipe: Forearm Profile Anchor

## Intent

Criar o primeiro perfil da ortese ancorado ao inicio do caminho principal, usando as medidas canonicas do antebraco e do punho.

## Por que esta recipe existe

A arvore atual ja mostra que o projeto possui uma base valida para perfil inicial do antebraco. Esse setup nao deve ficar enterrado numa area exploratoria da arvore; ele deve virar um pattern reutilizavel.

## Inputs

- `wrist_radius_mm`
- `forearm_radius_mm`
- `forearm_length_mm`
- `path_start_point`
- `path_start_tangent`
- `profile_offset_normal`
- `profile_rotation_offset_deg`
- `profile_scale_factor`

## Comportamento minimo

1. Gerar uma secao ou volume de referencia do antebraco.
2. Derivar o ponto inicial do caminho da ortese.
3. Alinhar o perfil a esse frame inicial.
4. Permitir um offset corretivo local sem perder a relacao de ancoragem.

## Fonte de verdade

O offset corretivo nao deve virar a regra principal. A fonte de verdade continua sendo o anchor do caminho.

## Outputs esperados

- `profile_geometry`
- `profile_anchor_point`
- `profile_anchor_frame`
- opcionalmente, debug markers

## Papel no projeto

Esta recipe ajuda a ligar tres coisas:

- medidas canonicas do antebraco;
- inicio do caminho da ortese;
- futura interface clinica de parametros.
