---
title: GN Diagnosis Protocol
applies_when: diagnosis,post_failure_recovery,clarification
topics: diagnosis,debug,problem,inspect,get_node_context,hypothesis,error,investigate
priority: high
lang: en
---
# Skill: Geometry Nodes Diagnosis

When the user describes a visual or behavioural problem:

1. **Reply in text first** — explain what you understood from the problem
2. **Describe what you will investigate** — which region of the tree, which nodes are suspect
3. **Use get_node_context** to read the suspect region
4. **Formulate a hypothesis** and present it to the user
5. **Only execute code** after the user confirms or does not object

Never jump straight to execute_code when receiving a problem description.
The textual diagnosis is part of the value delivered to the user.
