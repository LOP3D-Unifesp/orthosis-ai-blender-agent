---
title: GN Mutation Protocol
applies_when: mutation_request,mutation_confirmation,proposal
topics: mutation,execute_code,make_plan,verify,get_node_context
priority: high
lang: en
---
# Skill: Geometry Nodes Mutation

## Protocol: before / during / after

### Before modifying
1. make_plan — mandatory; execute_code is blocked without a plan
2. get_node_context — read the current state of the target node

### During the modification
1. One execute_code per atomic operation (Python/bpy only)
2. get_node_context after each execute_code to verify the result

### Stop and ask the user when you need:
- An anatomical coordinate or position
- An aesthetic decision (colour, shape, proportion)
- Visual approval of the result

### Never
- Invent anatomical values — always ask
- Repeat identical code after a failure — read state before correcting
- Ask for confirmation on routine GN operations — execute directly
