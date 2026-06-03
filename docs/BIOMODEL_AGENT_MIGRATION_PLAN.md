# Biomodel Agent Migration Plan

> Branch: `codex/biomodel-source-migration`
> Status: source-mode architecture accepted; Phase 1 scaffold implemented; awaiting manual Blender run
> Purpose: define the migration path from mutation drafts over a live Geometry Nodes tree to a canonical source-code-driven biomodel workflow.
> Governing decision: `docs/BIOMODEL_SOURCE_MODE_DECISION.md`

---

## 1. North Star

The final product should feel like this:

```text
User describes a clinical/geometric change
  -> agent updates the canonical biomodel source
  -> user reviews the source/draft
  -> user manually runs it
  -> generated Geometry Nodes tree is rebuilt
  -> user inspects result in Blender
```

The source of truth becomes code, not the hand-mutated live node tree.

Target artifacts:

| Artifact | Role |
|---|---|
| `GN_Biomodel_Source` | Blender Text block containing the canonical biomodel generator source |
| `VB_Biomodel_Generated` | generated Geometry Nodes tree, disposable/rebuildable |
| `Biomodelo` | current clinical/reference tree, initially read-only reference |
| `docs/CURRENT_TREE_BIOMODEL_INVENTORY.md` | extracted knowledge from the current tree |
| future `blender_addon/biomodel/*` | reusable DSL/helper implementation |

Core rule:

```text
The agent should edit source. The generated tree is an output.
```

Architecture rule:

```text
Biomodel source work is a separate source-mode product path, not an extension of the legacy GN_Agent_Draft mutation pipeline.
```

---

## 2. Product Boundary

There are now two paths in the add-on:

| Path | Status | Source of truth | Use when |
|---|---|---|---|
| `GN_Agent_Draft` mutation workflow | legacy | live GN tree + mutation draft | user explicitly asks to patch an existing tree |
| `GN_Biomodel_Source` workflow | primary for biomodel | complete source script | user asks to create/evolve/regenerate the biomodel |

The old draft path remains useful, but it should not keep absorbing biomodel-specific behavior. Biomodel-source requests should move toward a direct `biomodel_source_mode` handler and source-specific tools.

---

## 3. The Three Layers

There will not be three competing sources of truth. There will be one source, with three implementation layers below it.

### Layer 1: Our Biomodel DSL

This is the domain vocabulary we want the agent to use most of the time.

Example shape:

```python
model.parameter("Comp Antebraço", identifier="Socket_21", role="forearm_length")
model.region("Antebraço")
model.segment_cone("antebraco", length="Comp Antebraço", radius_start="Raio Cotovelo", radius_end="Raio Punho")
model.pose_rotation("wrist", axis="z", angle="Desvio Rad/Ulnar Punho")
model.output(...)
```

Purpose:

1. make code readable;
2. preserve clinical/anatomical intent;
3. keep repeated Geometry Nodes patterns out of the model source;
4. let the agent reason in biomodel terms instead of raw node operations.

### Layer 2: Node Authoring Backend

This is how the DSL turns concepts into actual nodes.

Options:

| Backend | Role |
|---|---|
| raw `bpy` | safest first implementation because Blender already has it |
| `nodebpy` | promising authoring layer, but optional until compatibility/licensing are decided |

Initial decision:

```text
Start with raw bpy inside our helper layer.
Treat nodebpy as reference/optional backend, not a hard dependency yet.
```

Why:

1. `nodebpy` requires Python `>=3.13`;
2. it is GPL-3.0-or-later;
3. we still need to verify Blender bundled Python compatibility;
4. the current add-on already works with `bpy`.

### Layer 3: Escape Hatch

The agent may still use raw `bpy` directly for exploration or unsupported cases, but this should be temporary.

Rule:

```text
If a raw bpy pattern becomes useful twice, promote it into the DSL/helper layer.
```

This avoids turning the DSL into a cage.

---

## 4. How The User Will Ask The Agent

### Legacy Mode: Draft Mutation

Today:

```text
"faz um script para mudar a árvore atual"
```

The agent writes a patch-style script against the current live tree.

This remains available during migration, but it is no longer the strategic path for the biomodel.

### Primary Mode: Biomodel Source

Target prompt style:

```text
"No GN_Biomodel_Source, adiciona controle de flexão do punho sem mexer na árvore Biomodelo original."
```

or:

```text
"Evolui o biomodel source para incluir o módulo de metacarpos usando os parâmetros atuais."
```

Expected behavior:

1. agent reads `GN_Biomodel_Source`;
2. agent reads exported/current inventory if needed;
3. agent updates the source;
4. source regenerates `VB_Biomodel_Generated`;
5. current `Biomodelo` is not mutated.
6. the old draft finalizer is not used to decide whether the source-mode turn succeeded.

### Exploration Prompt

When we do not know how to implement something:

```text
"Investiga uma forma de representar abertura dorsal progressiva no biomodel source. Não promova para DSL ainda; prototipa em helper separado."
```

Expected behavior:

1. agent can prototype with raw `bpy` or maybe `nodebpy`;
2. result is kept in experimental source/helper;
3. once useful, we promote it into DSL.

---

## 5. Migration Phases

We follow these phases in order. Do not skip to a later phase until the phase exit criteria are met.

### Phase 0: Stabilize Inspection

Status: complete for the migration baseline.

Goal:

Make sure the agent can see the whole current tree as an artifact, not just prompt fragments.

Already done:

1. `inspect_tree_inventory` added.
2. `export_tree_inventory` added.
3. current `Biomodelo` inventory exported.
4. first inventory document created.
5. test suite passes with the repository-local pytest scope.

Exit criteria:

1. `python -m pytest -q` passes.
2. `docs/CURRENT_TREE_BIOMODEL_INVENTORY.md` exists.
3. We have a conservative first generated source target: interface, frames, and representative forearm/wrist/hand geometry.

### Phase 1: Minimal Canonical Source

Goal:

Create `GN_Biomodel_Source` that generates a separate `VB_Biomodel_Generated` tree.

Current implementation:

1. `seed_biomodel_source` writes the initial source template into `GN_Biomodel_Source`.
2. The template lives in `blender_addon/biomodel/source_template.py`.
3. Running the source creates or replaces only `VB_Biomodel_Generated`.
4. `Biomodelo` remains a read-only reference by default.
5. The first source recreates all 39 interface parameters, creates region frames, and builds a small representative generated model.

Scope:

1. recreate the 39 interface parameters;
2. create one final `Geometry` output;
3. create region frames;
4. generate only a small representative geometry, not full parity.

Non-goals:

1. do not reproduce the full `Biomodelo` tree yet;
2. do not mutate `Biomodelo`;
3. do not introduce `nodebpy` as a required dependency.

Exit criteria:

1. `GN_Biomodel_Source` can be seeded into the Blender Text Editor. Done.
2. user can run `GN_Biomodel_Source` manually. Pending Blender validation.
3. `VB_Biomodel_Generated` appears in Blender. Pending Blender validation.
4. generated tree has the expected interface and output. Pending Blender validation.
5. source is readable enough for the agent to edit. Initial scaffold done.

### Phase 2: Isolated Source-Mode Tools And Handler

Goal:

Stop routing biomodel-source work through legacy draft mutation finalization.

Source-mode tools:

1. `seed_biomodel_source`;
2. `read_biomodel_source`;
3. `write_biomodel_source`;
4. `validate_biomodel_source`;
5. `inspect_generated_biomodel`.

Handler target:

```text
blender_addon/handler/biomodel_source.py
```

Behavior:

1. source-mode requests route directly to the source handler;
2. the handler reads/writes `GN_Biomodel_Source`;
3. it can call `inspect_tree_inventory` or read exported artifacts when needed;
4. it does not require `write_script_draft` to be called;
5. it does not use `draft_finalize.py` to interpret success/failure.

Exit criteria:

1. seed/read/write source works without relying on the legacy workspace finalizer;
2. source writes use source-specific validation;
3. temporary biomodel shortcuts can be removed from `handler/workspace.py`.

### Phase 3: Internal Helper Layer

Goal:

Move repeated raw `bpy` operations out of the source into reusable helpers.

Candidate package:

```text
blender_addon/biomodel/
  __init__.py
  dsl.py
  bpy_backend.py
  source_template.py
  validation.py
```

Early helper vocabulary:

```python
parameter(...)
region(...)
segment_box(...)
segment_cone(...)
segment_sphere(...)
pose_rotation(...)
join_region(...)
output(...)
```

Exit criteria:

1. `GN_Biomodel_Source` mostly reads like biomodel intent;
2. raw node creation is concentrated in `bpy_backend.py`;
3. tests cover helper output with fake/mocked Blender structures where possible.

### Phase 4: Module Parity From Current Tree

Goal:

Rebuild the current biomodel behavior module by module in generated source.

Order:

1. interface parameters;
2. forearm/wrist primitive region;
3. metacarpals;
4. finger chain 1;
5. finger chain 2;
6. thumb segments;
7. thumb pose;
8. wrist pose;
9. final assembly.

Exit criteria for each module:

1. generated nodes are readable;
2. parameter mapping is explicit;
3. module can be regenerated without touching `Biomodelo`;
4. behavior is visually inspected in Blender.

### Phase 5: Optional nodebpy Decision

Goal:

Decide whether `nodebpy` should become:

1. a dependency;
2. a vendored/submodule reference;
3. an optional experimental backend;
4. unused inspiration only.

Decision criteria:

1. Blender bundled Python compatibility;
2. installation complexity;
3. GPL/license implications;
4. readability gain over our raw `bpy` helper backend;
5. agent reliability.

Until this phase:

```text
nodebpy is not part of the production path.
```

---

## 6. Decision Rules

### When To Use The DSL

Use DSL/helper functions when the concept is stable:

1. parameter definitions;
2. anatomical regions;
3. repeated segment chains;
4. pose rotations;
5. joins/outputs.

### When To Use raw bpy

Use raw `bpy` when:

1. the helper layer does not exist yet;
2. a low-level Blender API detail is needed;
3. we are prototyping a new Geometry Nodes pattern.

Then promote repeated patterns into helpers.

### When To Use nodebpy

Use `nodebpy` only for an explicit experiment until Phase 5.

Do not make generated source require it before the dependency decision.

### When To Mutate The Current Tree

Only when the user explicitly asks to modify `Biomodelo`.

Default for migration:

```text
Read Biomodelo. Generate VB_Biomodel_Generated. Do not mutate Biomodelo.
```

### When To Use Legacy Draft Mutation

Use legacy draft mutation only when the user explicitly asks to alter, repair, or patch an existing live Geometry Nodes tree.

Do not use it as the default implementation path for the biomodel.

### When To Add Biomodel Behavior

Prefer adding new behavior to:

1. `blender_addon/biomodel/*`;
2. `blender_addon/tools/biomodel_source.py`;
3. future `blender_addon/handler/biomodel_source.py`.

Avoid adding biomodel-specific rules to `draft_finalize.py` or the old draft workspace unless it is a temporary compatibility bridge.

---

## 7. What We Do Next

Immediate next step:

```text
Finish Phase 1 manual validation, then implement Phase 2 source-mode isolation.
```

The prototype currently:

1. create or replace `VB_Biomodel_Generated`;
2. recreate the 39 current parameters;
3. create frames matching the current region labels;
4. generate a very small representative model;
5. be manually reviewable in Blender Text Editor.

After manual validation, implement the dedicated source-mode tool surface (`read_biomodel_source`, `write_biomodel_source`, `validate_biomodel_source`) and move source-mode routing out of the legacy workspace finalizer path.
