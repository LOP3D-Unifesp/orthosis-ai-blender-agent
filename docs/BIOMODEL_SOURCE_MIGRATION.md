# Biomodel Source Migration

> Branch: `codex/biomodel-source-migration`
> Criado: 2026-06-03
> **Direção revisada: 2026-06-10**
> Objetivo original: explorar um caminho onde um Python source canônico gera o biomodelo parametrizado.
> **Objetivo atual: construir o biomodelo incrementalmente sobre a árvore viva via bridge, consolidando em script mestre apenas quando seções estiverem validadas.**
> Decisão vigente: `docs/BIOMODEL_SOURCE_MODE_DECISION.md`

---

## 1. Por que esta branch existe

O caminho de agente embarcado (painel Blender → AgentRuntime → draft mutation) é útil mas
gerou complexidade antes de o biomodelo estar resolvido:

1. A árvore viva é a fonte da verdade.
2. O agente lê pedaços da árvore.
3. O agente escreve um script que muta a árvore.
4. O usuário roda manualmente.
5. A árvore muda e o próximo turno parte do estado modificado.

Quando a branch foi criada (2026-06-03), a aposta era inverter o centro de gravidade:

```text
source canônico → gera a árvore GN
```

Na prática, isso produziu o rebuild monolítico: cada turno reescrevia o script completo,
qualquer erro desfazia tudo e o ciclo de feedback ficou lento demais para exploração.

**A revisão de 2026-06-10 adota um caminho diferente:**

```text
árvore viva → patches incrementais via bridge → verificação imediata → consolidação eventual
```

O source canônico não desaparece — ele passa a ser o **artefato de consolidação**, não o loop.

---

## 2. Produto final

O produto técnico final continua sendo um script Python mestre executável no Blender,
capaz de gerar o biomodelo parametrizável de membro superior.

O caminho para chegar lá mudou:

| Antes (rebaixado) | Agora (primário) |
|---|---|
| Escrever source completo a cada prompt | Patchear a árvore viva incrementalmente |
| Rebuild monolítico como modo de experimentação | Rebuild como consolidação de seção pronta |
| Agente embarcado como interface | Claude Code + bridge como interface |
| Verificação depois de rodar o source completo | Verificação imediata após cada patch |

---

## 3. Arquitetura aceita (2026-06-10)

```text
primário:  Claude Code + BlenderConnection → patches incrementais → Biomodelo (árvore viva)
           ↓ quando seção validada
           consolidação: GN_Biomodel_Source → VB_Biomodel_Generated

legado:    GN_Agent_Draft → mutação via painel embarcado (disponível, não é o foco)
```

O designer opera via Claude Code (este ambiente).
O bridge (porta 65432, canal direto `HANDLERS`) é a superfície de execução.
O Blender é o ambiente de desenvolvimento, não o ambiente de produção do agente.

### Canal direto do bridge (sem policy gates)

```python
from blender_connection import BlenderConnection
conn = BlenderConnection()

# Inventariar
nodes = conn.list_tree_nodes("Biomodelo")

# Inspecionar
ctx = conn.get_node_context("Biomodelo", "Cube_Polegar1", radius=1)

# Patchear
result = conn.execute_code("""
import bpy
# PATCH: descrição
# ALVO: Biomodelo / NomeDoNó
# RISCO: baixo
tree = bpy.data.node_groups.get("Biomodelo")
node = tree.nodes.get("NomeDoNó")
antes = node.inputs[0].default_value
node.inputs[0].default_value = novo_valor
print(f"ANTES: {antes}  DEPOIS: {node.inputs[0].default_value}")
print("OK" if node.inputs[0].default_value == novo_valor else "FAIL")
""")
```

### Convenção de patch incremental

Cada patch deve:
1. Ser um script Python autocontido (namespace fresco a cada `execute_code`).
2. Fazer **uma** alteração estrutural (um nó, uma conexão, um conjunto de valores relacionados).
3. Ter `assert` defensivo antes de qualquer mutação.
4. Imprimir estado anterior e verificar o resultado dentro do próprio script.
5. Imprimir `OK` ou `FAIL` explicitamente.

Após cada patch: re-leitura via `get_node_context` ou `list_tree_nodes` confirma que
a mudança está persistida no `bpy.data`.

---

## 4. O que aprender da árvore atual

Antes de patchear, é preciso mapear o que existe.
A árvore `Biomodelo` tem atualmente 126 nós, 139 links, 10 frames, 6 grupos.

Ferramentas de inspeção disponíveis:

```python
conn.list_tree_nodes("Biomodelo")          # inventário completo, sem cap
conn.find_tree_nodes("Biomodelo", label_contains="antebraço")  # busca focal
conn.get_node_context("Biomodelo", "NomeDoNó", radius=2)       # vizinhança
```

Para inspeção full-tree e extração de DSL (via `runtime_tool_call`):

```text
inspect_tree_inventory(section="overview")
inspect_tree_inventory(section="parameters")
inspect_tree_inventory(section="regions")
inspect_tree_inventory(section="nodes", offset=0, limit=40)
export_tree_inventory(tree_name="Biomodelo")  → runtime/tree_inventory/
```

O `CURRENT_TREE_BIOMODEL_INVENTORY.md` já existe como primeiro registro.

---

## 5. Fases de trabalho

### Fase 0: ciclo mínimo de pilotagem — CONCLUÍDO (2026-06-10)

O ciclo foi validado via `smoke_bridge.py`:
1. Bridge responde (ping).
2. `list_tree_nodes` lista a árvore real (126 nós).
3. `get_node_context` inspeciona um nó real.
4. `execute_code` roda patch inofensivo.
5. Patch real com alteração + restauração + re-leitura via bridge: 5/5 OK.

### Fase 1: inspeção e mapeamento da árvore

Objetivo: entender a estrutura atual da `Biomodelo` por região antes de propor patches.

Tarefas:
1. Usar `list_tree_nodes` + `get_active_frame_context` por frame para mapear cada região.
2. Identificar nós de parâmetro, nós de geometria, nós de join por região.
3. Registrar quais nós têm inputs numéricos simples (alvos para parametrização).
4. Identificar a primeira região para evoluir (candidato: Antebraço — mais simples).

### Fase 2: patches incrementais por região

Objetivo: evoluir a árvore viva região por região via bridge.

Regras:
1. Um patch = um script = uma alteração estrutural.
2. Cada patch é verificado antes do próximo.
3. Snapshot `.blend` antes de patches que afetam muitos nós.
4. Patches que funcionam ficam registrados no histórico da conversa.

### Fase 3: consolidação em source

Objetivo: serializar seções validadas em `GN_Biomodel_Source`.

Trigger: quando uma região está visualmente validada no Blender e os parâmetros estão estáveis.

Ferramentas:
- `export_tree_inventory` → extrai inventário da região como referência.
- `write_biomodel_source` → escreve o source consolidado.
- `validate_biomodel_source` → valida invariantes antes de salvar.

### Fases futuras (em espera)

As fases abaixo do plano original (DSL, helper layer, nodebpy, parity completo)
continuam válidas como direção de longo prazo mas não estão em andamento.
Serão retomadas quando a árvore viva estiver bem mapeada e as primeiras seções
tiverem sido evoluídas com sucesso via patches incrementais.

---

## 6. Próximos passos imediatos

1. Mapear a árvore por região: listar frames, nós por frame, parâmetros por região.
2. Escolher a primeira região para evoluir (candidato: `Antebraço`).
3. Inspecionar essa região via bridge (`get_active_frame_context` + `get_node_context`).
4. Propor e executar o primeiro patch real de construção (não só smoke test).
5. Verificar, iterar, e só consolidar quando a região estiver estável.

**O que não fazer agora:**
- Não escrever `GN_Biomodel_Source` completo antes de ter seções prontas.
- Não implementar DSL, nodebpy ou helper layer ainda.
- Não refatorar o agente embarcado.
- Não implementar rollback sofisticado antes de provar valor dos patches.
