---
title: Clinical Motion Parameters
applies_when: mutation_request,clarification,proposal
topics: clinical,parameters,wrist,radial,ulnar,flexion,extension,deviation,hand,proxy
priority: medium
lang: pt
---
# Parametros Clinicos de Movimento para o Biomodelo Proxy

## Objetivo

Este arquivo define a linguagem parametrica que deve substituir controles geometricos arbitrarios da arvore. A ideia nao e construir um simulador biomecanico completo. A ideia e expor controles clinicamente inteligiveis, consistentes e reaproveitaveis.

## Regra principal

Cada parametro deve cair em uma destas familias:

1. **shape** - descreve tamanho e proporcao
2. **pose** - descreve angulacao e configuracao da mao
3. **orthosis** - descreve offsets e relacoes da ortese
4. **anchor** - descreve frames e pontos de referencia que conectam shape, pose e ortese

## 1. Parametros globais do punho

### `wrist_radial_ulnar_deg`
- unidade: graus
- neutro: `0`
- atua sobre: conjunto distal da mao em relacao ao antebraco
- observacao: deve orientar tambem anchors relevantes da ortese

### `wrist_flex_ext_deg`
- unidade: graus
- neutro: `0`
- atua sobre: conjunto distal da mao em relacao ao antebraco
- observacao: deve afetar biomodelo e curvas da ortese a partir do mesmo frame

## 2. Parametros de grupos da mao

A mao nao deve ser tratada como um bloco unico. A divisao em grupos laterais e importante para formar os arcos da palma e depois orientar a ortese.

### `hand_radial_group_spread_deg`
- unidade: graus
- atua sobre: lado radial da mao
- papel: abrir ou fechar o arco do lado radial

### `hand_ulnar_group_spread_deg`
- unidade: graus
- atua sobre: lado ulnar da mao
- papel: abrir ou fechar o arco do lado ulnar

### `palm_arch_radial_mm`
- unidade: mm
- atua sobre: curvatura e relevo do lado radial da palma

### `palm_arch_ulnar_mm`
- unidade: mm
- atua sobre: curvatura e relevo do lado ulnar da palma

## 3. Parametros dos metacarpos

O projeto precisa permitir controle por grupo e, mais tarde, por dedo quando necessario.

### Familia inicial
- `metacarpal_radial_flex_deg`
- `metacarpal_ulnar_flex_deg`

### Evolucao desejada
- `metacarpal_1_flex_deg`
- `metacarpal_2_flex_deg`
- `metacarpal_3_flex_deg`
- `metacarpal_4_flex_deg`
- `metacarpal_5_flex_deg`

Esses parametros ajudam a construir o arco da mao e a orientar a borda da ortese.

## 4. Parametros das falanges

Para os dedos 2 a 5, o sistema deve prever pelo menos estes niveis:

- `proximal`
- `middle`
- `distal`

### Familias iniciais simplificadas
- `phalanges_radial_proximal_flex_deg`
- `phalanges_radial_middle_flex_deg`
- `phalanges_radial_distal_flex_deg`
- `phalanges_ulnar_proximal_flex_deg`
- `phalanges_ulnar_middle_flex_deg`
- `phalanges_ulnar_distal_flex_deg`

### Evolucao desejada por dedo
- `finger_2_proximal_flex_deg`
- `finger_2_middle_flex_deg`
- `finger_2_distal_flex_deg`
- repetir para dedos `3`, `4` e `5`

## 5. Parametros do polegar

O polegar deve ser tratado separadamente.

### Minimo inicial
- `thumb_base_fold_deg`
- `thumb_middle_fold_deg`
- `thumb_tip_fold_deg`

### Evolucao desejada
- `thumb_abduction_deg`
- `thumb_opposition_deg`
- `thumb_rotation_deg`

## 6. Parametros antropometricos essenciais

Os primeiros valores ja existentes e que devem seguir canonicos sao:

- `wrist_radius_mm`
- `forearm_radius_mm`
- `forearm_length_mm`

Tambem sao candidatos naturais:

- `palm_width_mm`
- `palm_length_mm`
- `digit_length_scale_*`
- `thumb_length_scale`

## 7. Parametros derivados para a ortese

Esses parametros nao descrevem so o corpo. Eles ajudam a mover as curvas e perfis da ortese junto com o biomodelo.

Eles devem ser conectados ao sistema definido em `knowledge/domain/canonical_anchor_system.md`.

Exemplos:
- `orthosis_path_start_anchor`
- `orthosis_path_mid_anchor`
- `orthosis_path_hand_anchor`
- `forearm_profile_anchor`
- `thumb_opening_anchor`
- `palm_border_offset_mm`

## Recomendacao de implementacao

### Primeiro passo
Comecar com poucos controles fortes:
- punho global
- grupo radial da mao
- grupo ulnar da mao
- polegar separado
- medidas basicas do antebraco e punho

### Segundo passo
Promover familias para parametros por dedo e por segmento.

### Terceiro passo
Fazer curvas e perfis da ortese consumirem o mesmo sistema de anchors e parametros.

## Como guardar cada parametro

Cada parametro maduro deve ter:
- `machine_id`
- `display_label`
- `unit`
- `neutral_value`
- `range_min`
- `range_max`
- `category`
- `affected_region`
- `mapping_note`

## Aviso importante

Esses controles devem ser apresentados como parametros de projeto e configuracao clinicamente inspirados. Eles nao substituem avaliacao clinica nem modelagem biomecanica validada.
