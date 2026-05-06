---
title: GN Navigation Strategy
applies_when: baseline_refresh,clarification,diagnosis,mutation_request
topics: navigation,tree,nodes,get_node_context,get_scene_summary,tokens,baseline,cost
priority: medium
lang: en
---
# Skill: GN Tree Navigation

## Cost per tool

| Tool | Tokens (~) | When to use |
|---|---|---|
| get_scene_summary | ~1,000 | Starting point — find out what exists in the scene |
| get_node_context(radius=1) | ~2,000 | Known name/label, post-mutation verification |
| get_node_context(radius=2) | ~4,000 | Need to see indirect connections |
| get_local_subgraph_context | ~2,000-6,000 | Focused subgraph by node list or neighborhood |

## Navigation strategy

- **No context at all** → get_scene_summary first, then get_node_context on the target
- **Name/label known** → get_node_context directly
- **Need wider view** → get_local_subgraph_context with a small radius, not the full tree
- **After execute_code** → always verify with get_node_context on the modified node
