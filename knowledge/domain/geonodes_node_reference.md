---
title: GN Node Tree Reference
applies_when: diagnosis,clarification,baseline_refresh
topics: tree,nodes,structure,reference,path,profile,subsystem,bezier
priority: medium
lang: pt
---
# Geometry Nodes — Referência de Nós do Projeto

> Lido diretamente via MCP de `Geometry Nodes.001` — `geonode ort v2.blend`, Blender 5.1.0.
> Atualizar sempre que o node tree principal evoluir.
> Este arquivo é injetado no system_prompt para reduzir alucinação sobre API de nós.

---

## Node group: `Geometry Nodes.001`

**Objeto host:** `Plane` — mesh 4 verts, modificador `GeometryNodes`
**Biomodelo de referência:** `Ideal` — 39.370 verts / 78.736 faces, rotação 90° em X
**Curva auxiliar:** `BézierCurve` — oculta, sem modificadores

### Interface do grupo

| Dir | Nome | Tipo | Identificador |
|-----|------|------|---------------|
| INPUT | Geometry | NodeSocketGeometry | `Socket_0` |
| INPUT | Largura B.A. | NodeSocketFloat | `Socket_3` |
| INPUT | Extensão Antebraço | NodeSocketVector | `Input_2` |
| OUTPUT | Geometry | NodeSocketGeometry | `Socket_1` |

---

## Arquitetura geral — dois subsistemas paralelos

O tree gera dois tipos de geometria que convergem num `Join Geometry` final:

```
[SUBSISTEMA A — CAMINHO]  Bezier Segment (antebraço) + Bezier Segment Hand (mão)
                                          ↓
                                  Resample Curve Hand → Join Geometry → Group Output
                                                                ↑
[SUBSISTEMA B — PERFIL]   Bézier Segment → Transform Geometry ──┘
                          (perfil transversal, posicionado ao longo do caminho)
```

---

## Subsistema A — Caminho da Órtese

Gera o caminho longitudinal completo do antebraço até a mão.
Composto por **dois segmentos Bézier com continuidade C1** na junção.

### Segmento A — `Bezier Segment` (label: "Caminho Geral")

| Parâmetro | Fonte | Observação |
|-----------|-------|------------|
| `Start` | `Group Input.001 → Extensão Antebraço` | Vetor group input |
| `End` | `Vec_Ponto_Juncao` | Ponto de junção com segmento B |
| `End Handle` | `Vec_EndHandle_Antebr` | Controla tangente de chegada na junção |
| `Start Handle` | hardcoded | `[0, -116.8, 20.3]` — a ajustar |
| Mode | OFFSET | handles são offsets relativos aos endpoints |

### Segmento B — `Bezier Segment Hand`

| Parâmetro | Fonte | Observação |
|-----------|-------|------------|
| `Start` | `Vec_Ponto_Juncao` | Compartilhado com End do Segmento A |
| `Start Handle` | `VM_G1_Add` | **Computado automaticamente** — espelho C1 |
| `End Handle` | hardcoded | `[0, -89.3, 52.29]` — a ajustar |
| `End` | hardcoded | `[0, -148.1, -31.1]` — a ajustar |
| Mode | POSITION | handles são posições absolutas |

### Cadeia G1 — continuidade C1 na junção

Garante que os handles dos dois segmentos formem uma linha reta através do ponto de junção,
eliminando kinks visíveis. Padrão documentado em `raciocinio_g1_continuidade.md`.

```
Vec_EndHandle_Antebr ──→ VM_G1_Subtract (SUBTRACT, primeiro input = [0,0,0])
                                ↓
                         VM_G1_Scale (SCALE, valor = 1.0)
                                ↓
Vec_Ponto_Juncao ──────→ VM_G1_Add (ADD)
                                ↓
                    Bezier Segment Hand → Start Handle
```

**Fórmula:** `Start_Handle_B = Vec_Ponto_Juncao + (−Vec_EndHandle_Antebr × tensão)`

**CRÍTICO:** `VM_G1_Subtract` recebe `[0,0,0]` no primeiro Vector input (desconectado).
Conectar `Vec_Ponto_Juncao` nesse socket recria o bug do loop (double-add na junção).

### Nós de parâmetros do caminho

| Nome | Label | Valor atual | Papel |
|------|-------|-------------|-------|
| `Vec_Ponto_Juncao` | Vec_Ponto_Juncao | `[0, -21.3, -25.3]` | Posição absoluta da junção punho |
| `Vec_EndHandle_Antebr` | Vec_EndHandle_Antebr | `[0, 16.1, -14.7]` | Handle de chegada (offset, modo POSITION) |

### Pipeline do caminho

```
Bezier Segment (Caminho Geral)
  → Resample Curve (64 pts)
  → Sample Curve  ──────────────────────────── usado pelo Subsistema B
  → Reroute → Reroute.001 → Join Geometry

Bezier Segment Hand
  → Resample Curve Hand (64 pts)
  → Join Geometry → Group Output
```

---

## Subsistema B — Perfil da Órtese

Gera a seção transversal e a posiciona ao longo do caminho via `Sample Curve`.
Atualmente representa o **início da primeira curva do perfil** (região do antebraço).

### Bézier Segment do perfil — `Bézier Segment` (sem label)

| Parâmetro | Fonte | Valor atual |
|-----------|-------|-------------|
| `Start` | `Vector Math.001` (Add_Start) | Center + offX_start |
| `End` | `Vector Math.002` (Add_End) | offY + offX_end |
| `Start Handle` | hardcoded | `[-28.3, 180.0, -40.7]` |
| `End Handle` | hardcoded | `[35.6, 180.0, -43.3]` |
| Mode | POSITION | |
| Resolution | 24 | |

### Lógica de construção do perfil

```
Vector.004 (Start Base [36.4, 180, 0])  ┐
                                          ├→ Sum_SE → Center (×0.5)
Vector.005 (End_Base [-27.8, 180, 0])   ┘
                                                ↓
Largura B.A. → half (×0.5) ──→ offX_end  (Xdir × +half) → pEnd_X  → Add_End  → Bézier End
                           └──→ negHalf (×-1) → offX_start (Xdir × -half) → pStart_X → Add_Start → Bézier Start

Vector [0,1,0] → offY (SCALE por y_shift=0.0) → Add_Start e Add_End
```

### Posicionamento do perfil no espaço

```
Bezier Segment (caminho) → Resample Curve → Sample Curve
                                                 ↓ Position
                                           Separate XYZ (SepY_caminho) → Y
                                                                           ↓
Center → Separate XYZ.001 (SepY_center) → Y → Math (dY = SUBTRACT) → Combine XYZ (só Y)
                                                                              ↓
                                                                    Transform Geometry (Translation)
                                                                              ↓
                                                             Bézier Segment → Transform → Join Geometry
```

---

## Inventário completo — 39 nós

### Curvas (6)

| Nome | Label | bl_idname | Mode | Papel |
|------|-------|-----------|------|-------|
| `Bezier Segment` | Caminho Geral | GeometryNodeCurvePrimitiveBezierSegment | OFFSET | Segmento A — antebraço |
| `Bezier Segment Hand` | Bezier Segment Hand | GeometryNodeCurvePrimitiveBezierSegment | POSITION | Segmento B — mão |
| `Bézier Segment` | — | GeometryNodeCurvePrimitiveBezierSegment | POSITION | Perfil transversal |
| `Resample Curve` | — | GeometryNodeResampleCurve | Count=64 | Reamostra caminho antebraço |
| `Resample Curve Hand` | Resample Curve Hand | GeometryNodeResampleCurve | Count=64 | Reamostra caminho mão |
| `Sample Curve` | — | GeometryNodeSampleCurve | FACTOR | Lê posição no caminho |

### Geometria (2)

| Nome | bl_idname | Papel |
|------|-----------|-------|
| `Transform Geometry` | GeometryNodeTransform | Translada perfil para posição no caminho |
| `Join Geometry` | GeometryNodeJoinGeometry | Une caminho mão + perfil posicionado |

### Vetores constantes (6)

| Nome | Label | Valor | Papel |
|------|-------|-------|-------|
| `Vector` | — | `[0, 1, 0]` | Direção Y para offset do perfil |
| `Vector.003` | Xdir | `[1, 0, 0]` | Direção X para offsets laterais |
| `Vector.004` | Start Base | `[36.4, 180.0, 0]` | Base de partida do perfil |
| `Vector.005` | End_Base | `[-27.8, 180.0, 0]` | Base de chegada do perfil |
| `Vec_Ponto_Juncao` | Vec_Ponto_Juncao | `[0, -21.3, -25.3]` | Junção antebraço–mão |
| `Vec_EndHandle_Antebr` | Vec_EndHandle_Antebr | `[0, 16.1, -14.7]` | Handle de chegada no punho |

### Vector Math (11)

| Nome | Label | Operação | Papel |
|------|-------|----------|-------|
| `Vector Math` | offY | SCALE | Offset do perfil em Y |
| `Vector Math.001` | Add_Start | ADD | Start do perfil |
| `Vector Math.002` | Add_End | ADD | End do perfil |
| `Vector Math.003` | Sum_SE | ADD | Start Base + End_Base |
| `Vector Math.004` | Center | SCALE 0.5 | Centro do perfil |
| `Vector Math.005` | offX_end | SCALE | Offset +X do perfil |
| `Vector Math.006` | offX_start | SCALE | Offset −X do perfil |
| `Vector Math.007` | pStart_X | ADD | Center + offX_start |
| `Vector Math.008` | pEnd_X | ADD | Center + offX_end |
| `VM_G1_Subtract` | VM_G1_Subtract | SUBTRACT | Negação do handle — `[0,0,0] − Vec_EndHandle_Antebr` |
| `VM_G1_Scale` | VM_G1_Scale | SCALE 1.0 | Tensão G1 (1.0 = C1 exato) |
| `VM_G1_Add` | VM_G1_Add | ADD | `Vec_Ponto_Juncao + handle negado` |

### Escalares (4)

| Nome | Label | Operação / Valor | Papel |
|------|-------|------------------|-------|
| `Math` | dY | SUBTRACT | Delta Y caminho vs centro perfil |
| `Math.001` | half | MULTIPLY 0.5 | Metade da Largura B.A. |
| `Math.002` | negHalf | MULTIPLY −1 | Metade negativa da Largura B.A. |
| `Value` | y_shift - Em mm | constante 0.0 | Shift manual Y do perfil |

### Utilitários (10)

| Nome | bl_idname |
|------|-----------|
| `Separate XYZ` (SepY_caminho) | ShaderNodeSeparateXYZ |
| `Separate XYZ.001` (SepY_center) | ShaderNodeSeparateXYZ |
| `Combine XYZ` (DeltaY) | ShaderNodeCombineXYZ |
| `Group Input` | NodeGroupInput |
| `Group Input.001` | NodeGroupInput |
| `Group Output` | NodeGroupOutput |
| `Reroute` / `Reroute.001` / `Reroute.002` | NodeReroute |

---

## Armadilhas críticas

### VM_G1_Subtract — primeiro input DEVE ser [0,0,0]
Não conectar `Vec_Ponto_Juncao` no primeiro socket deste nó.
Isso produziria `2×Ponto_Juncao − Handle` em vez de `Ponto_Juncao − Handle`, gerando loop.

### OFFSET vs POSITION nos Bezier Segments
`Bezier Segment` (Caminho Geral): modo **OFFSET** — handles são deslocamentos relativos ao ponto.
`Bezier Segment Hand` e `Bézier Segment` (perfil): modo **POSITION** — handles são posições absolutas.
Misturar sem consciência gera curvas inesperadas.

### Identificadores de socket mudam ao recriar o grupo
Sempre resolver por nome via `interface.items_tree`. Nunca hardcode `Socket_N`.

### Atualizar viewport após modificação de parâmetro
Após `mod[ident] = value`, chamar `obj.data.update_tag()` + `bpy.context.view_layer.update()`.

---

## Próximos passos previstos

- Expandir caminho com segmentos C1 adicionais para dedos / regiões complexas da mão
- Conectar caminho ao perfil via `Curve to Mesh` para gerar superfície bruta da órtese
- Aplicar padrão G1 ao perfil da mão (múltiplos segmentos com 3 handlers de controle)
- Expor parâmetros chave como group inputs para controle via modificador
