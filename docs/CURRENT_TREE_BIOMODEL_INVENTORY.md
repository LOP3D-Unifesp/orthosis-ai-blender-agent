# Current Tree Biomodel Inventory

> Source export:
> `runtime/tree_inventory/Biomodelo_20260603T0108400000.json`
> `runtime/tree_inventory/Biomodelo_20260603T0108400000.md`
>
> Tree: `Biomodelo`
> Exported at: `2026-06-03T01:08:40+00:00`

---

## 1. Executive Reading

The current Geometry Nodes tree looks like a **parametric upper-limb biomodel scaffold**, not yet a full orthosis/shell generator.

The dominant structure is:

```text
primitive anatomical solids -> transforms -> region joins -> hand/forearm assembly -> Geometry output
```

Inventory counts:

| Item | Count |
|---|---:|
| Nodes | 123 |
| Links | 139 |
| Frames | 7 |
| Node groups | 0 |
| Interface inputs | 39 |
| Interface outputs | 1 |
| Live modifier parameters | 39 |

Node type distribution:

| Type | Count | Reading |
|---|---:|---|
| `ShaderNodeMath` | 51 | Position/anchor/scale math dominates the tree |
| `ShaderNodeCombineXYZ` | 20 | Transform vectors/rotations are built manually |
| `GeometryNodeTransform` | 17 | Anatomical primitives are positioned/rotated |
| `GeometryNodeMeshCube` | 11 | Cubes represent metacarpal/falange/thumb segments |
| `GeometryNodeJoinGeometry` | 9 | Regional and final assembly |
| `NodeFrame` | 7 | Existing modular hints |
| `NodeGroupInput` | 5 | Repeated interface access points |
| `NodeGroupOutput` | 1 | Single final geometry output |
| `GeometryNodeMeshUVSphere` | 1 | Wrist/carpo primitive |
| `GeometryNodeMeshCone` | 1 | Forearm primitive |

Initial conclusion:

The current tree is a strong source for extracting a first biomodel DSL because it already encodes:

1. clinical/interface parameters;
2. anatomical regions;
3. segment primitives;
4. transform/anchor math patterns;
5. assembly order.

It is not a good final source of truth because it repeats low-level node patterns, has no node groups, and uses many generic internal node names.

---

## 2. Existing Regions

The frame labels are more useful than the internal frame names. A future source/DSL should preserve the labels semantically, not depend on `Frame.00x` names.

| Proposed module | Current frame | Child count | Current role |
|---|---|---:|---|
| `forearm_region` | `Antebraço` / `Frame` | 5 | Forearm cone + wrist/carpo sphere + transforms |
| `thumb_segments` | `Polegar` / `Frame.003` | 7 | Thumb metacarpal/proximal/distal solids and raw join |
| `thumb_pose` | `Flex/Ext e Abd Polegar` / `Frame.002` | 2 | Thumb abduction and flex/extension transforms |
| `wrist_pose` | `Desvio e Ext/Flex Punho` / `Frame.004` | 6 | Radial/ulnar deviation and wrist flex/extension |
| `finger_chain_1` | `Falanges1` / `Frame.005` | 16 | One metacarpal/finger chain with phalange segments |
| `finger_chain_2` | `Falanges 2` / `Frame.006` | 16 | Second finger chain with phalange segments |
| `metacarpals` | `Metacarpos` / `Frame.001` | 11 | Metacarpal solids and local scale/position math |

Important assembly nodes outside frames:

| Node | Role |
|---|---|
| `Join_MaoBruta` | Aggregates thumb, metacarpals, and falanges |
| `TF_DesvioUlnar` | Applies radial/ulnar wrist deviation to hand assembly |
| `TF_ExtensaoFlexao` | Applies wrist flex/extension after deviation |
| `Join_Geral.004` | Joins forearm and wrist/carpo region |
| `Join_Geral` | Joins forearm/wrist assembly with posed hand assembly |
| `Join_Geral.002` | Final join before `Group Output` |

Observed final geometry path:

```text
Join_Polegar + Join_Metacarpos + Join_Falanges
  -> Join_MaoBruta
  -> TF_DesvioUlnar
  -> TF_ExtensaoFlexao

TF_Punho.001 + TF_Antebraco.001
  -> Join_Geral.004

TF_ExtensaoFlexao + Join_Geral.004
  -> Join_Geral
  -> Join_Geral.002
  -> Group Output.Geometry
```

---

## 3. Parameter Inventory

All current interface inputs are `NodeSocketFloat`. The interface default is often `0.0`, while the live modifier value carries the useful current value. That distinction matters for a source generator.

### Forearm / Wrist

| Parameter | Identifier | Live value | Proposed role |
|---|---|---:|---|
| `Comp Antebraço` | `Socket_21` | 223.8100 | forearm length |
| `Raio Cotovelo` | `Socket_22` | 37.3000 | proximal forearm radius |
| `Raio Punho` | `Socket_23` | 24.8000 | wrist/distal forearm radius |
| `Desvio Rad/Ulnar Punho` | `Socket_24` | -2.6000 | wrist radial/ulnar deviation angle/control |
| `Flex/Ext Punho` | `Socket_25` | 0.0000 | wrist flexion/extension angle/control |

### Palm / Metacarpals

| Parameter | Identifier | Live value | Proposed role |
|---|---|---:|---|
| `Curva Palma Metacarpo 1` | `Socket_27` | 0.0000 | palm/metacarpal curve control |
| `Curva Palma Metacarpo 2` | `Socket_28` | 0.0000 | palm/metacarpal curve control |
| `Comp Metacarpo` | `Socket_29` | 95.2700 | metacarpal length |
| `Largura Metacarpo` | `Socket_30` | 30.8300 | metacarpal/palm width |
| `Espessura Metacarpo` | `Socket_31` | 35.6300 | metacarpal thickness/depth |

### Thumb

| Parameter | Identifier | Live value | Proposed role |
|---|---|---:|---|
| `Comp Metacarpo Polegar` | `Socket_33` | 0.0000 | thumb metacarpal length |
| `Largura Metacarpo Polegar` | `Socket_34` | 0.0000 | thumb metacarpal width |
| `Espessura Metacarpo Polegar` | `Socket_35` | 0.0000 | thumb metacarpal thickness |
| `Flex/Ext Polegar` | `Socket_36` | 3.5900 | thumb flexion/extension |
| `Abdução Polegar` | `Socket_37` | 15.0000 | thumb abduction |
| `Flex/Ext Falange Prox Polegar` | `Socket_38` | 0.0000 | thumb proximal phalanx angle |
| `Flex/Ext Falange Dist Polegar` | `Socket_39` | 0.0000 | thumb distal phalanx angle |
| `Comp Falange Prox Polegar` | `Socket_40` | 0.0000 | thumb proximal phalanx length |
| `Espessura Falange Prox Polegar` | `Socket_42` | 0.0000 | thumb proximal phalanx thickness |
| `Comp Falange Dist Polegar` | `Socket_43` | 0.0000 | thumb distal phalanx length |
| `Espessura Falange Dist Polegar` | `Socket_45` | 0.0000 | thumb distal phalanx thickness |

### Finger Chain 1

| Parameter | Identifier | Live value | Proposed role |
|---|---|---:|---|
| `Flex/Ext Falange Prox 1` | `Socket_47` | 0.0000 | proximal phalanx angle |
| `Flex/Ext Falange Media 1` | `Socket_48` | 0.0000 | middle phalanx angle |
| `Flex/Ext Falange Dist 1` | `Socket_49` | 0.0000 | distal phalanx angle |
| `Comp Falange Prox 1` | `Socket_50` | 0.0000 | proximal phalanx length |
| `Espessura Falange Prox 1` | `Socket_52` | 0.0000 | proximal phalanx thickness |
| `Comp Falange Media 1` | `Socket_53` | 0.0000 | middle phalanx length |
| `Espessura Falange Media 1` | `Socket_55` | 0.0000 | middle phalanx thickness |
| `Comp Falange Dist 1` | `Socket_56` | 0.0000 | distal phalanx length |
| `Espessura Falange Dist 1` | `Socket_58` | 0.0000 | distal phalanx thickness |

### Finger Chain 2

| Parameter | Identifier | Live value | Proposed role |
|---|---|---:|---|
| `Flex/Ext Falange Prox 2` | `Socket_60` | 0.0000 | proximal phalanx angle |
| `Flex/Ext Falange Media 2` | `Socket_61` | 0.0000 | middle phalanx angle |
| `Flex/Ext Falange Dist 2` | `Socket_62` | 0.0000 | distal phalanx angle |
| `Comp Falange Prox 2` | `Socket_63` | 0.0000 | proximal phalanx length |
| `Espessura Falange Prox 2` | `Socket_65` | 0.0000 | proximal phalanx thickness |
| `Comp Falange Media 2` | `Socket_66` | 0.0000 | middle phalanx length |
| `Espessura Falange Media 2` | `Socket_68` | 0.0000 | middle phalanx thickness |
| `Comp Falange Dist 2` | `Socket_69` | 0.0000 | distal phalanx length |
| `Espessura Falange Dist 2` | `Socket_71` | 0.0000 | distal phalanx thickness |

Parameter concern:

The identifiers skip numbers (`Socket_26`, `Socket_32`, etc.). This may be normal Blender interface churn, but the migration should treat existing names/identifiers as a compatibility contract until we intentionally define a cleaner parameter schema.

---

## 4. Patterns To Promote Into DSL

### 4.1 Primitive Segment

Current pattern:

```text
Mesh primitive -> Transform -> regional JoinGeometry
```

Examples:

| Primitive | Transform | Region |
|---|---|---|
| `Cone_Antebraco.001` | `TF_Antebraco.001` | Antebraço |
| `UVSphere_Punho.001` | `TF_Punho.001` | Antebraço/Punho |
| `Cube_Metacarpo1.001` | `TF_Metacarpo1.001` | Metacarpos |
| `Cube_Polegar1` | `TF_Polegar1` | Polegar |
| `Cube_Falange11` | `TF_Falange11` | Falanges1 |

Potential DSL:

```python
model.segment_box(name, length, width, thickness, anchor, orientation)
model.segment_cone(name, length, radius_start, radius_end, anchor)
model.segment_sphere(name, radius, anchor)
```

### 4.2 Segment Chain Anchor Math

Current pattern for metacarpals/falanges:

```text
Half length -> positive anchor -> negative anchor -> CombineXYZ vector -> Transform
Ponta/base accumulates chain length for next segment
```

Examples:

| Current node | Meaning candidate |
|---|---|
| `HalfComp_MC1` | half length for first metacarpal placement |
| `AnchorY_MC1` | Y anchor for first metacarpal |
| `NegAnchor_MC1` | negative Y offset for transform vector |
| `PontaMC_Base` | base/end point for downstream phalanx chains |
| `AnchorFP1`, `AnchorFM1`, `AnchorFD1` | chain anchors for proximal/middle/distal segments |

Potential DSL:

```python
chain = model.segment_chain("finger_1", base_anchor="metacarpal_base")
chain.add_segment("metacarpal", length=..., width=..., thickness=...)
chain.add_segment("proximal_phalanx", length=..., thickness=..., flexion=...)
chain.add_segment("middle_phalanx", length=..., thickness=..., flexion=...)
chain.add_segment("distal_phalanx", length=..., thickness=..., flexion=...)
```

### 4.3 Pose Transforms

Current pattern:

```text
angle parameter -> RADIANS math -> CombineXYZ rotation vector -> Transform
```

Examples:

| Parameter | Math | Rotation vector | Transform |
|---|---|---|---|
| `Desvio Rad/Ulnar Punho` | `Math_UlnarRad` | `CXYZ_UlnarRot` | `TF_DesvioUlnar` |
| `Flex/Ext Punho` | `Math_ExtFlexRad` | `CXYZ_ExtFlexRot` | `TF_ExtensaoFlexao` |
| `Abdução Polegar` | `Math_AbdRad` | `CXYZ_AbdRot` | `TF_AbducaoPolegar` |
| `Flex/Ext Polegar` | `Math_ExtFlexPolegarRad` | `CXYZ_ExtFlexPolegarRot` | `TF_ExtFlexPolegar` |

Potential DSL:

```python
model.pose_rotation(region="wrist", axis="z", angle="Desvio Rad/Ulnar Punho")
model.pose_rotation(region="wrist", axis="x", angle="Flex/Ext Punho")
model.pose_rotation(region="thumb", axis="z", angle="Abdução Polegar")
model.pose_rotation(region="thumb", axis="x", angle="Flex/Ext Polegar")
```

### 4.4 Regional Assembly

Current pattern:

```text
Join_Polegar_Raw -> thumb pose -> Join_Polegar
Join_Metacarpos + Join_Falanges + Join_Polegar -> Join_MaoBruta
Join_MaoBruta -> wrist pose transforms -> final assembly
```

Potential DSL:

```python
hand = model.join_region("raw_hand", [thumb, metacarpals, finger_1, finger_2])
posed_hand = model.apply_pose_chain(hand, [thumb_pose, wrist_deviation, wrist_flexion])
model.output(model.join_region("biomodel", [forearm, wrist, posed_hand]))
```

---

## 5. Proposed Canonical Anchors

The automatic anchor list is noisy. Many candidates are ordinary operational nodes. These should be treated as a starting point, not truth.

Proposed canonical anchors to validate:

| Proposed anchor | Evidence in current tree | Confidence |
|---|---|---|
| `forearm_axis` | `Cone_Antebraco.001`, `TF_Antebraco.001` | medium |
| `wrist_center` | `UVSphere_Punho.001`, `TF_Punho.001`, `Raio Punho` | high |
| `hand_base` | `Raio Punho`, `Comp Metacarpo`, `PontaMC_Base` | medium |
| `metacarpal_1_base` | `AnchorY_MC1`, `NegAnchor_MC1`, `TF_Metacarpo1.001` | medium |
| `metacarpal_2_base` | `AnchorY_MC2`, `NegAnchor_MC2`, `TF_Falange21.001` | medium |
| `finger_1_proximal_anchor` | `AnchorFP1` | medium |
| `finger_1_middle_anchor` | `AnchorFM1` | medium |
| `finger_1_distal_anchor` | `AnchorFD1` | medium |
| `finger_2_proximal_anchor` | `AnchorFP2` | medium |
| `finger_2_middle_anchor` | `AnchorFM2` | medium |
| `finger_2_distal_anchor` | `AnchorFD2` | medium |
| `thumb_base` | `TF_Polegar1`, `TF_AbducaoPolegar`, `TF_ExtFlexPolegar` | medium |

Open issue:

These anchors are mathematical construction points, not necessarily clinical landmarks. Before freezing the DSL, we should decide which anchors are clinical concepts and which are implementation helpers.

---

## 6. Candidate Invariants

These are the first rules that should survive migration to `GN_Biomodel_Source`.

1. The generated tree must keep one final `Geometry` output.
2. Existing public parameter names/identifiers should be preserved or migrated explicitly.
3. The region labels should remain stable: `Antebraço`, `Polegar`, `Flex/Ext e Abd Polegar`, `Desvio e Ext/Flex Punho`, `Falanges1`, `Falanges 2`, `Metacarpos`.
4. Degrees-to-radians conversion must remain explicit for rotation controls.
5. Segment chain positioning must remain cumulative: each phalanx is placed relative to upstream segment length/anchor.
6. Hand assembly should remain separable from forearm/wrist assembly before final join.
7. Early source-generation work should create a separate generated tree, not mutate the clinical tree directly.
8. Interface defaults and live modifier values must be handled separately; current live values are not the same thing as socket defaults.

---

## 7. Current Tree Weak Spots

These are not criticisms of the biomodel idea; they are signs that the tree wants to become source-generated.

| Weak spot | Why it matters |
|---|---|
| No node groups | Repeated finger/thumb/segment logic is not encapsulated |
| 51 math nodes | Hard for the agent to reason about without a higher-level representation |
| 53 unframed nodes | Important assembly/anchor math lives outside frames |
| Generic internal names | `Math.031`, `Combine XYZ.010`, `Frame.005` are fragile anchors |
| Duplicate/repeated `Group Input` nodes | Normal in GN, but noisy for agent reasoning |
| Interface identifiers have gaps | Suggests prior edits; migration needs explicit parameter mapping |
| Interface defaults often `0.0` | Live modifier values are the meaningful current values |
| No shell/orthosis phase detected | The tree appears to model anatomical volumes, not final orthosis geometry |

---

## 8. First DSL Direction

Do not start with a giant clinical DSL. Start with a biomodel source layer that captures the repeated patterns already visible.

Candidate first vocabulary:

```python
model.parameter(name, identifier=None, default=0.0, role="")
model.region(name, label="")
model.segment_box(name, length, width, thickness, anchor="")
model.segment_cone(name, length, radius_start, radius_end, anchor="")
model.segment_sphere(name, radius, anchor="")
model.segment_chain(name, base_anchor="")
model.pose_rotation(region, axis, angle_parameter)
model.join_region(name, parts)
model.output(geometry)
```

Minimum first prototype:

1. Generate a new tree, not the current `Biomodelo`.
2. Recreate the public interface with the 39 current parameters.
3. Recreate only the high-level regions and a few representative primitives.
4. Keep the generated tree visually separate and disposable.
5. Compare generated structure against this inventory before attempting parity.

---

## 9. Next Analysis Questions

Before writing source code, validate these in Blender:

1. Are `Falanges1` and `Falanges 2` meant to represent two fingers, or two digit chains within a simplified hand?
2. Are `Curva Palma Metacarpo 1/2` currently connected to meaningful geometry, or reserved for future palm curvature?
3. Should `Raio Punho` define both wrist sphere radius and metacarpal base offsets?
4. Are `Comp/Largura/Espessura Metacarpo Polegar` intentionally zero because thumb dimensions are not active yet?
5. Which current anchor math nodes correspond to clinical landmarks versus construction helpers?
6. Where should the orthosis shell stage begin after this biomodel tree?

