# PHASE6_NOTES.md

> Phase 6 of `REFATOR_PLAN.md` — Knowledge Retrieval Layer.
> Status: complete for Phase 6 scope. The system remains runnable.
> Verification: `python -m unittest discover -s tests` → 222 tests (218 pass, 2 skip, 2 pre-existing errors).

---

## What changed

### 1. Front-matter added to all 12 knowledge files

All Markdown files in `knowledge/` now carry a YAML-like header block:

```
---
title: <human-readable title>
applies_when: <comma-separated turn-class strings>
topics: <comma-separated scoring keywords>
priority: high | medium | low
lang: en | pt
---
```

Files updated:

| File | Category | Priority | Lang |
|---|---|---|---|
| `skills/gn_mutation.md` | skills | high | **en** (translated) |
| `skills/gn_diagnosis.md` | skills | high | **en** (translated) |
| `skills/gn_navigation.md` | skills | medium | **en** (translated) |
| `recipes/forearm_profile_anchor.md` | recipes | high | pt |
| `recipes/shared_bezier_transition.md` | recipes | high | pt |
| `domain/geonodes_node_reference.md` | domain | medium | pt |
| `domain/geonodes_ortese.md` | domain | high | pt |
| `domain/padrao_g1_continuidade.md` | domain | high | pt |
| `domain/clinical_motion_parameters.md` | domain | high | pt |
| `domain/current_tree_anchor_mapping.md` | domain | medium | pt |
| `domain/canonical_anchor_system.md` | domain | medium | pt |
| `domain/learned_patterns.md` | domain | medium | pt |

English translations were limited to the three `skills/` files — the
domain/recipes corpus was not bulk-translated (deferred to a future pass).

### 2. New `blender_addon/knowledge/` subpackage

**`knowledge/__init__.py`** — public API:
```python
from .corpus import KnowledgeItem
from .retriever import KnowledgeRetriever
```

**`knowledge/corpus.py`** — typed corpus loader:
- `KnowledgeItem` dataclass: `title`, `content`, `applies_when`, `topics`,
  `priority`, `lang`, `path`, `category`
- `KnowledgeCorpus(corpus_dir)` — scans `skills/`, `recipes/`, `domain/`
  subdirectories; results cached after first load
- `parse_front_matter(text)` — regex-based parser; strips UTF-8 BOM; returns
  `(fields_dict, body_text)` without a YAML library dependency

**`knowledge/retriever.py`** — scored, budget-aware retriever:
- `KnowledgeRetriever(corpus_dir)` — wraps a `KnowledgeCorpus`
- `retrieve(*, session, turn_class, message, budget_tokens=1000)` returns
  items sorted by score descending, clipped to token budget; items scoring 0
  are excluded entirely
- `_score(item, session, turn_class, message)` — scoring logic:
  - `turn_class in item.applies_when` → +10.0 (strongest signal)
  - multiplied by `priority_weight` (high=×2, medium=×1, low=×0.5)
  - topic keyword overlap with message tokens → +1.5 per match
  - `skills` category bonus +5.0 / `recipes` bonus +3.0 when any topic matches
  - session focus `tree_name` appears in item content → +3.0

### 3. `TurnContext.retrieve_knowledge()` — new helper

Added to `blender_addon/runtime/handlers/__init__.py`:

```python
def retrieve_knowledge(self, *, budget_tokens: int = 900) -> list[dict]:
    from ...knowledge import KnowledgeRetriever
    corpus_root = self.knowledge_dir.parent   # knowledge/domain/ → knowledge/
    if not corpus_root.is_dir():
        return []
    retriever = KnowledgeRetriever(corpus_root)
    turn_class = str(getattr(self.meta, "turn_class", ""))
    items = retriever.retrieve(
        session=self.session,
        turn_class=turn_class,
        message=self.message,
        budget_tokens=budget_tokens,
    )
    return [{"title": item.title, "content": item.content} for item in items]
```

### 4. Five handlers updated

Each of the five handlers that build a system prompt now retrieves knowledge
before calling `build_system_prompt`:

```python
# Before (Phase 3–5):
system = build_system_prompt(ctx.session, "mutation_request")

# After (Phase 6):
knowledge = ctx.retrieve_knowledge()
system = build_system_prompt(ctx.session, "mutation_request", knowledge=knowledge)
```

Handlers updated:
- `handlers/mutation_request.py`
- `handlers/diagnosis.py`
- `handlers/proposal.py`
- `handlers/clarification.py`
- `handlers/post_failure_recovery.py`

### 5. `context_knowledge.py` — tombstoned

No live code paths imported this module after Phase 3.  Replaced with
module-level `__getattr__` raising `ImportError` with a redirect message.

### 6. `runtime_context.py` — tombstoned

Re-exported from `context_knowledge.py` (also tombstoned).  Same treatment.

### 7. `tests/test_knowledge_phase6.py` — new test suite

32 new tests covering:

| Group | Tests |
|---|---|
| `TestParseFrontMatter` | fields parsed; body stripped; no-FM fallback; CSV parsing |
| `TestKnowledgeCorpus` | list returned; all subdirs read; cache hit; fields populated; content no FM; empty dir; ignores non-md |
| `TestKnowledgeRetriever` | returns list; turn_class match; no match excluded; zero-score excluded; budget respected; topic overlap; priority ordering; focus bonus; sorted descending |
| `TestTurnContextRetrieveKnowledge` | returns list[dict]; missing dir returns []; turn_class forwarded |
| `TestTombstoneGuardsPhase6` | context_knowledge raises; runtime_context raises |
| `TestLiveKnowledgeFiles` | 12 files present; all have title; all have applies_when; gn_mutation en; gn_diagnosis en; gn_navigation en; corpus loads all 12 |

---

## Surfaces that remain

| Module | Status | Notes |
|---|---|---|
| `knowledge/corpus.py` | **Live — canonical** | Front-matter parser + loader |
| `knowledge/retriever.py` | **Live — canonical** | Scored retrieval |
| `knowledge/__init__.py` | **Live** | Public re-export |
| `handlers/__init__.py` | **Live** | `TurnContext.retrieve_knowledge()` added |
| `context_knowledge.py` | Tombstoned | Keyword-regex selector removed |
| `runtime_context.py` | Tombstoned | Legacy facade removed |

---

## What is deferred to Phase 7+

### Corpus translation campaign
All `domain/` and `recipes/` files are still Portuguese.  Only the three
`skills/` files were translated.  A full translation pass is deferred — it is
a content task, not an architecture task.

### Token counting
The retriever uses a rough `chars / 4` estimate.  If a real tokeniser
(tiktoken or Anthropic's) is available, the budget check would be more
accurate.  Deferred — the estimate is sufficient for the current corpus size.

### Retriever tuning
Score weights (`+10`, `×2`, `+1.5`, `+5`, `+3`) are not calibrated against
real turns.  A follow-up pass with evaluation data could improve retrieval
quality.
