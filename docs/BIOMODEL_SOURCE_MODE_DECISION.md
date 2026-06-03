# Biomodel Source Mode Decision

> Branch: `codex/biomodel-source-migration`
> Status: accepted for this branch
> Decision date: 2026-06-03

---

## 1. Decision

The primary path for the biomodel is now a separate source-driven workflow:

```text
GN_Biomodel_Source -> VB_Biomodel_Generated
```

The existing draft-mutation workflow remains available as legacy infrastructure, but it is no longer the strategic path for building the parametrized upper-limb biomodel.

This means:

1. `GN_Biomodel_Source` is the canonical biomodel source.
2. `VB_Biomodel_Generated` is disposable output.
3. `Biomodelo` is a read-only clinical/reference tree by default.
4. The agent should edit source, not patch the live clinical tree.
5. The old `GN_Agent_Draft` workflow is legacy for general/manual tree mutation tasks.
6. The new source mode should not be forced through finalizers that expect `write_script_draft` against `GN_Agent_Draft`.

---

## 2. Why

The old architecture solves a harder and different product problem:

```text
read partial live tree -> write mutation script -> user runs it -> live tree changes -> repeat
```

That path needs routing, context gates, structural memory, draft validation, repair loops, pending decisions, rollback expectations, and safety rules because the source of truth is a mutable Blender node tree.

The biomodel-source path is simpler:

```text
read source + optional reference inventory -> write complete source -> user runs source -> generated tree is rebuilt
```

Trying to fit this new product into the old draft-mutation pipeline already caused unnecessary coupling: a seed request for `GN_Biomodel_Source` was judged by a finalizer that only knew how to look for `write_script_draft`.

That is the architectural signal this branch accepts.

---

## 3. Product Boundary

### Legacy: Draft Mutation

Legacy path:

```text
GN_Agent_Draft -> mutates an existing live Geometry Nodes tree
```

Use it only when the user explicitly asks to patch or repair an existing live tree.

It may continue to use:

1. `handler/workspace.py` draft goals;
2. `draft_policy.py`;
3. `draft_finalize.py`;
4. `write_script_draft`;
5. `read_script_draft`;
6. focused node reads;
7. repair/feedback loops.

Do not grow this path for biomodel-source work unless the change is a small compatibility fix.

### Primary: Biomodel Source Mode

Primary path:

```text
GN_Biomodel_Source -> generates VB_Biomodel_Generated
```

Use it when the user asks to create, evolve, parametrize, regenerate, or reason about the biomodel source.

It should have a small direct surface:

1. seed source;
2. read source;
3. write complete source;
4. inspect/export reference tree inventory;
5. validate source invariants;
6. optionally inspect generated tree after manual execution.

It should not depend on:

1. `GN_Agent_Draft`;
2. live-tree mutation as the main behavior;
3. old draft finalization rules;
4. focal node reads as the default source of truth;
5. automatic execution of generated Python.

---

## 4. Reuse Map

### Keep And Reuse

| Area | How it helps source mode |
|---|---|
| Blender socket bridge | stable connection to Blender |
| Text Editor write/read primitives | useful for `GN_Biomodel_Source` storage |
| `inspect_tree_inventory` | complete reference-tree navigation |
| `export_tree_inventory` | offline source/DSL extraction artifact |
| `operation_journal` | debug trace for source-mode turns |
| session/chat persistence | keeps UI and history stable |
| snapshots | still useful before manual execution |
| tests/fake bpy harness | safe local regression testing |
| `blender_addon/biomodel/*` | home for source template, DSL, backend, validation |

### Legacy But Keep Available

| Area | Legacy role |
|---|---|
| `GN_Agent_Draft` | mutation-script Text block |
| draft workspace goals | general tree mutation and repair |
| `draft_policy.py` | safety gates for mutation drafts |
| `draft_finalize.py` | old write/no-write interpretation |
| feedback repair loop | post-run repair of mutation drafts |
| focal node reads | targeted investigation of existing trees |

### Avoid For New Source Mode

| Area | Reason |
|---|---|
| treating prompt summaries as full tree context | loses structure |
| patching `Biomodelo` by default | wrong source of truth |
| using `GN_Agent_Draft` as biomodel source | mixes products |
| requiring `write_script_draft` finalization | couples source mode to legacy draft semantics |
| introducing `nodebpy` as a dependency now | compatibility/license still undecided |

---

## 5. Source Mode Target Architecture

Initial shape:

```text
blender_addon/
  biomodel/
    __init__.py
    source_template.py       # current phase-1 seed template
    dsl.py                   # future biomodel vocabulary
    bpy_backend.py           # future raw bpy node authoring backend
    validation.py            # future source/generated-tree invariants

  tools/
    biomodel_source.py       # source-mode tools

  handler/
    biomodel_source.py       # future direct source-mode turn handler
```

Current transitional state:

1. `tools/biomodel_source.py` exists and can seed `GN_Biomodel_Source`.
2. `source_template.py` exists and generates `VB_Biomodel_Generated`.
3. `handler/workspace.py` has a temporary direct shortcut for `seed_biomodel_source`.

Target state:

1. source-mode requests route to `handler/biomodel_source.py`;
2. source-mode tools do not depend on legacy draft finalization;
3. `GN_Biomodel_Source` read/write has explicit validation for source invariants;
4. the old workspace handler does not need biomodel-specific shortcuts.

---

## 6. Invariants

These rules define correctness for this branch:

1. `Biomodelo` is not mutated unless the user explicitly asks.
2. `GN_Biomodel_Source` is the only canonical source for the generated biomodel.
3. `VB_Biomodel_Generated` can be deleted and recreated.
4. Source-mode writes are complete-source writes, not tiny patch fragments.
5. Manual execution remains the default safety boundary.
6. Inventory artifacts are reference knowledge, not a replacement for source.
7. Stable raw `bpy` patterns can be promoted into the DSL/helper layer.
8. `nodebpy` remains optional until a later decision.

---

## 7. Implementation Plan

### Phase A: Declare The Boundary

Status: in progress.

1. Add this decision document.
2. Update migration docs to mark draft mutation as legacy.
3. Identify reused modules vs legacy modules.

### Phase B: Isolate Source Tools

Goal:

Create a small source-mode tool surface independent from old draft finalization.

Tools:

1. `seed_biomodel_source`;
2. `read_biomodel_source`;
3. `write_biomodel_source`;
4. `validate_biomodel_source`;
5. `inspect_generated_biomodel`.

Exit:

The seed/read/write path works without the model needing to call `write_script_draft` directly.

### Phase C: Direct Source Handler

Goal:

Route source-mode user requests into a dedicated handler.

Behavior:

1. detect source-mode intent;
2. read current source;
3. read inventory only when needed;
4. ask the model for a full revised source;
5. write source with source-specific validation;
6. respond with a concise review summary.

Exit:

No biomodel-source request depends on the legacy draft workspace finalizer.

### Phase D: Source Validation

Goal:

Before saving, enforce source invariants.

Initial checks:

1. source mentions `GN_Biomodel_Source`;
2. generated tree name is `VB_Biomodel_Generated`;
3. source does not target/remove `Biomodelo`;
4. source defines all required interface parameters;
5. source creates one Geometry output;
6. source compiles as Python outside Blender.

### Phase E: Helper/DSL Extraction

Goal:

Move repeated raw `bpy` authoring into `blender_addon/biomodel/`.

Start with:

1. parameters;
2. regions;
3. primitive segment nodes;
4. joins;
5. pose transforms.

### Phase F: Module Parity

Goal:

Rebuild the reference tree behavior module by module in source:

1. interface;
2. forearm/wrist;
3. metacarpals;
4. finger chains;
5. thumb;
6. wrist/thumb poses;
7. final assembly.

---

## 8. Next Concrete Step

Implement Phase B:

```text
read_biomodel_source
write_biomodel_source
validate_biomodel_source
```

Then move the temporary seed shortcut out of `handler/workspace.py` into a dedicated source-mode handler.
