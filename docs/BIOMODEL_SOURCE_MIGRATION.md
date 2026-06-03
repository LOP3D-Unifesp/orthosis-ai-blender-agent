# Biomodel Source Migration

> Branch: `codex/biomodel-source-migration`
> Created: 2026-06-03
> Goal: explore a healthier agent path where a canonical Python source generates the parametrized upper-limb biomodel, instead of the agent only producing incremental mutation scripts for an already-live Geometry Nodes tree.
> Governing decision: `docs/BIOMODEL_SOURCE_MODE_DECISION.md`

---

## 1. Why This Branch Exists

The current agent path is useful but fragile:

1. The Blender node tree is the main source of truth.
2. The agent reads pieces of that tree.
3. The agent writes a Python draft that mutates the tree.
4. The user manually runs the draft.
5. The tree changes, and the next turn starts from the modified tree.

This can become hard to reason about because knowledge is spread across the live tree, the draft, session memory, execution history, and user intent.

This branch explores a different center of gravity:

```text
canonical biomodel source -> generated Geometry Nodes tree
```

In this model, the tree is an output. The source code is the stable artifact the agent edits, reviews, versions, and regenerates.

---

## 2. Desired Product Shape

The user should be able to say what the biomodel needs to do clinically or geometrically, even when they do not know how to implement it in Geometry Nodes.

The agent should be able to work at multiple levels:

1. Clinical DSL level: stable domain concepts such as forearm shell, wrist transition, metacarpal support, clearance, openings, borders, anchors.
2. Node-authoring level: `nodebpy` or a similar builder API for readable Geometry Nodes construction.
3. Raw `bpy` level: escape hatch for Blender API details not covered by the higher-level layers.

The DSL must not become a cage. It should represent stable knowledge already discovered in the biomodel. New or unknown requests should be prototyped at the lower levels, then promoted into the DSL only after they become reliable.

---

## 3. Accepted Architecture

This branch no longer treats biomodel-source work as a small variation of the old draft-first mutation workflow.

The accepted architecture is:

```text
legacy path:  GN_Agent_Draft      -> mutates an existing live tree
primary path: GN_Biomodel_Source  -> generates VB_Biomodel_Generated
```

The legacy path remains available for explicit live-tree patching. The primary biomodel path should be smaller, more direct, and source-driven.

Current legacy:

```text
GN_Agent_Draft = script that mutates the existing node tree
```

Primary biomodel source:

```text
GN_Biomodel_Source = canonical source that builds/regenerates the biomodel tree
```

The user still reviews and runs code manually. The agent still writes to the Blender Text Editor. The difference is that `GN_Biomodel_Source` is not a one-off patch; it is the evolving source of the generated model.

Generated target:

```text
VB_Biomodel_Generated
```

The generated tree can be recreated from the source, making behavior easier to audit and reproduce.

Important boundary:

```text
Do not keep growing draft-mutation finalizers to support biomodel-source work.
```

Source-mode requests should move toward dedicated source tools and a dedicated handler.

---

## 4. What We Need To Learn From The Current Tree

Before designing a DSL, we should mine the existing Geometry Nodes tree for concrete structure.

The agent should not rely only on focal reads for this phase. It needs a deliberate full-tree inspection path:

```text
inspect_tree_inventory(section="overview")
inspect_tree_inventory(section="parameters")
inspect_tree_inventory(section="regions")
inspect_tree_inventory(section="nodes", offset=0, limit=40)
inspect_tree_inventory(section="links", offset=0, limit=60)
inspect_tree_inventory(section="anchors")
inspect_tree_inventory(section="invariants")
```

The tool is paginated on purpose. The full tree is read directly from Blender, then exposed to the model in navigable sections so we do not lose important structure to prompt truncation.

Important distinction:

```text
tree_structural_memory = local persisted structural memory
prompt_context         = bounded summary sent to the model in a normal draft turn
inspect_tree_inventory = paginated access to the full inventory when the model needs it
export_tree_inventory  = JSON + Markdown artifact for offline review and DSL extraction
```

The agent should never treat a prompt summary as if it had seen the entire tree. For source/DSL extraction, full-tree inventory must be consulted explicitly.

Recommended first Blender prompt:

```text
Exporte o inventario completo da arvore Geometry Nodes atual para JSON e Markdown usando export_tree_inventory. Nao explique a arvore no chat; apenas retorne os caminhos dos arquivos e as contagens principais.
```

Expected output location:

```text
runtime/tree_inventory/
```

Key inventories:

1. Parameters
   - Which interface inputs already exist?
   - Which are clinical controls?
   - Which are internal technical controls?
   - Which need units, ranges, or defaults?

2. Regions / modules
   - Which node clusters correspond to anatomical or geometric regions?
   - Example candidates: forearm, wrist, hand, metacarpals, thumb, transitions, shell thickness, openings, borders.

3. Anchors
   - Which named nodes, frames, points, curves, or parameters act as stable references?
   - Which names should become canonical?
   - Which names are accidental or implementation-specific?

4. Invariants
   - What must remain true after any generated change?
   - Examples: final geometry exists, required regions stay connected, minimum thickness is respected, clinical clearance affects internal volume, canonical anchors are not renamed casually.

5. Generation strategy
   - Can the whole tree be regenerated safely?
   - Should early versions generate only a new experimental tree?
   - Should existing live trees remain untouched until the source is trusted?

---

## 5. Migration Phases

### Phase 0: Branch And Map

Status: complete for the first migration baseline.

Tasks:

1. Keep `main` stable.
2. Keep `nodebpy/` experimental and untracked unless we explicitly decide to vendor/submodule it.
3. Document the new direction.
4. Run the current agent test suite separately from `nodebpy/tests`.
5. Add and validate a full-tree inspection tool for source/DSL extraction.
6. Produce a current-tree inventory from Blender/runtime tools.

Definition of done:

1. Current tests still pass with `python -m pytest tests -q`.
2. The agent can inspect the whole GN tree by paginated sections instead of only focal neighborhoods.
3. We have a first inventory of parameters, regions, anchors, and invariants.
4. We have not changed the live agent behavior yet.

### Phase 1: Canonical Source Scaffold

Create a minimal source script that can generate a simple biomodel tree.

Candidate text block:

```text
GN_Biomodel_Source
```

Candidate generated tree:

```text
VB_Biomodel_Generated
```

The first source does not need to reproduce the full current tree. It should prove the workflow:

1. Source lives in the Text Editor.
2. User reviews and runs it manually.
3. It creates or replaces a generated GN tree.
4. It exposes a small parameter interface.
5. It is readable enough for the agent to revise.

Current scaffold:

1. `seed_biomodel_source` writes `GN_Biomodel_Source`.
2. The source creates or replaces only `VB_Biomodel_Generated`.
3. The source recreates the 39 current interface parameters and one geometry output.
4. The source creates the current region frames and representative forearm/wrist/hand geometry.
5. Manual execution inside Blender is still required before treating this as visually validated.

### Phase 2: Source-Mode Isolation

Add dedicated source-mode tools and a handler branch for biomodel source work.

It should:

1. Read `GN_Biomodel_Source`.
2. Read relevant current-tree context when needed.
3. Write a complete revised source.
4. Avoid mutating the current clinical tree directly.
5. Avoid the legacy `GN_Agent_Draft` finalizer path.
6. Validate source-mode invariants directly.

Initial tool surface:

```text
seed_biomodel_source
read_biomodel_source
write_biomodel_source
validate_biomodel_source
inspect_generated_biomodel
```

### Phase 3: DSL Extraction

After enough source code repeats, extract stable helpers.

Possible examples:

```python
model.parameter(...)
model.anchor(...)
model.region(...)
model.add_shell(...)
model.add_transition(...)
model.add_opening(...)
```

The rule: only promote patterns into the DSL after they are useful and tested.

### Phase 4: Current Tree Parity

Gradually reproduce important behavior from the current tree in the generated biomodel source.

This should happen module by module, not as a big rewrite:

1. Interface parameters.
2. Core guide/anchor structure.
3. Forearm region.
4. Wrist transition.
5. Hand/metacarpal region.
6. Thickness and clearance.
7. Openings and borders.
8. Final cleanup/output.

---

## 6. Immediate Next Steps

Recommended next actions:

1. Seed `GN_Biomodel_Source` from Blender with `seed_biomodel_source`.
2. Review the generated source in the Text Editor.
3. Run it manually and confirm `VB_Biomodel_Generated` appears.
4. Inspect the generated tree interface and output.
5. Implement the isolated source-mode read/write/validation tools.
6. Move source-mode routing into a dedicated handler.
7. Choose the first module to move toward parity, probably forearm/wrist because it is the simplest high-value region.

Current preference:

```text
Prototype with the least dependency risk first.
Use nodebpy as a reference and possible middle layer, but do not couple the main addon to it until Python/Blender compatibility and licensing are understood.
```
