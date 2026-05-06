---
title: Learned Patterns
applies_when: mutation_request,mutation_confirmation,diagnosis
topics: learned,pattern,node_input,configuration,name,property,input
priority: medium
lang: pt
---
# Padrões Aprendidos — Geometry Nodes

> Gerado automaticamente pelo knowledge_updater.
> Cada padrão foi extraído de uma sessão bem-sucedida.

---

## Padrão: Configuração de Entrada de Nó por Nome

Acesso e modificação de propriedades de entrada em nós de Geometry Nodes através de referência nominal:

1. Localizar nó específico na árvore de nós (`tree.nodes[nome]`)
2. Acessar entrada pelo atributo `inputs[nome_entrada]`
3. Atribuir valor via `default_value` com tipo compatível (Vector3 para escala)
4. Verificar resultado da atribuição por leitura da propriedade

**Aplicação:** Configuração programática de parâmetros de transformação e efeitos geométricos.

---

