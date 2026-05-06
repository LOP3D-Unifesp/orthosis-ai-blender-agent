# Arquitetura de Agentes — Projeto Órtese

## Raciocínio

Cada fase da órtese tem vocabulário de nós diferente, padrões de decisão
diferentes, e contexto de erro diferente. Um único agente generalista
desperdiça janela de contexto carregando conhecimento irrelevante para a fase atual.

Agentes especializados por fase:
- Recebem apenas o contexto relevante para aquela fase
- Têm ferramentas autorizadas diferentes (ex: Fase 3 pode criar furos; Fase 1 não)
- Compartilham estado via `scene_snapshot.md` e `geonodes_node_reference.md`
- Podem ser substituídos/atualizados independentemente

---

## Agente 0 — Orquestrador de Sessão

**Papel:** Decide qual agente de fase ativar. Lê o estado atual da cena e
determina em qual fase o projeto está, ou qual fase o usuário quer trabalhar.

**Ferramentas:** `get_scene_summary`, `get_tree_structure`

**Lê:**
- `geonodes_ortese.md` (estado geral do projeto)
- `scene_snapshot.md` (estado atual da cena)

**Decide:** qual agente especializado ativar + passa o contexto relevante

**Quando usar:** início de cada sessão de trabalho

---

## Agente 1 — Curvas (Esqueleto)

**Fase:** 1 — Curvas principais

**Especialidade:** Bézier Segments, continuidade G1, caminhos longitudinais,
perfis transversais, parâmetros anatômicos.

**Ferramentas autorizadas:**
- `get_tree_structure`, `get_scene_summary`, `analyze_gn_state` (leitura)
- `connect_nodes`, `disconnect_nodes` (conexões)
- `set_node_value`, `create_node` (quando disponíveis)
- `execute_blender_code` (somente com `enable_mcp_writes` explícito)

**Lê obrigatoriamente:**
- `rules/geonodes_node_reference.md`
- `rules/padrao_g1_tres_handlers.md`
- `context/scene_snapshot.md`

**Modo de operação:**
- Autônomo para operações de nós (connect, set_value, create)
- Instruído para posicionamento de handles e pontos anatômicos
- Diagnóstico sempre antes de modificar estrutura do grupo

**Gatilhos para modo instruído (não executa, descreve):**
- Ajuste de `Vec_Ponto_Juncao` — requer referência no mesh do paciente
- Ajuste de handles de angulação — requer julgamento estético/anatômico
- Qualquer operação que dependa de ver o resultado no viewport

---

## Agente 2 — Lofting (Malha Bruta)

**Fase:** 2 — Malha bruta entre perfis

**Especialidade:** `Curve to Mesh`, interpolação de perfis, `Resample Curve`,
`Sample Curve`, `Instance on Points`, topologia da superfície.

**Lê obrigatoriamente:**
- `rules/geonodes_node_reference.md`
- `rules/padrao_g1_tres_handlers.md` (perfis complexos usam o mesmo padrão)
- `context/scene_snapshot.md`

**Modo de operação:**
- Mais autônomo que o Agente 1 — a topologia é mais determinística
- Instruído para ajuste de forma dos perfis em regiões específicas (polegar, punho)

**Pré-requisito para ativar:** Agente 1 concluído e `scene_snapshot.md` atualizado.

---

## Agente 3 — Furos de Ventilação

**Fase:** 3 — Furos

**Especialidade:** `Distribute Points`, `Voronoi Texture`, `Delete Geometry`,
`Raycast`, operações booleanas em GN, distância à borda.

**Parâmetros que controla:**
- Forma dos furos
- Tamanho e densidade
- Distância mínima da borda (restrição rígida)

**Modo de operação:** Predominantemente autônomo — a lógica é procedural
e determinística. Pouco julgamento anatômico necessário.

**Pré-requisito para ativar:** Agente 2 concluído, malha bruta fechada.

---

## Agente 4 — Espessura e Finalização

**Fase:** 4 — Espessura + preparação para impressão

**Especialidade:** `Solidify` / equivalente GN, verificação de manifold,
exportação para impressão 3D.

**Modo de operação:** Autônomo — operação única e bem definida.

**Pré-requisito para ativar:** Agente 3 concluído.

---

## Estado compartilhado entre agentes

```
context/
  scene_snapshot.md      ← atualizado por qualquer agente ao fim de uma fase
  scene_snapshot.json    ← idem

rules/
  geonodes_node_reference.md   ← atualizado quando novos nós são adicionados
  geonodes_ortese.md           ← atualizado quando fases mudam de estado
```

**Regra:** nenhum agente começa sem ler `scene_snapshot.md`.
**Regra:** nenhum agente termina sem rodar o inspector e atualizar o snapshot.

---

## Quando um agente instrui vs executa

| Situação | Agente faz |
|----------|-----------|
| Sabe o nó, sabe o valor, é reversível | Executa via MCP |
| Envolve posição anatômica no espaço 3D | Instrui o usuário |
| Operação destrutiva ou irreversível | Propõe + aguarda confirmação |
| Estado ambíguo / nó inesperado | Diagnóstico primeiro |
| Loop visual, scale errado, link errado | Corrige direto via MCP |

---

## Implementação no Claude Code

Cada agente é um **Claude Project** separado com:
- `CLAUDE.md` contendo o system_prompt especializado da fase
- Acesso apenas às ferramentas MCP relevantes para aquela fase
- Os arquivos de `rules/` e `context/` no contexto do projeto

O Agente 0 (Orquestrador) pode ser implementado como uma tool no addon do Blender
que detecta a fase atual e abre a conversa no Project correto.
