# Biomodel Agent Migration Plan

> Branch: `codex/biomodel-source-migration`
> Status original (2026-06-03): source-mode aceito, Phase 1 scaffold implementado.
> **Status revisado (2026-06-10): caminho primário é patches incrementais via bridge. Source-mode é consolidação.**
> Decisão vigente: `docs/BIOMODEL_SOURCE_MODE_DECISION.md`

---

## 1. North Star (revisado 2026-06-10)

O produto final continua sendo o mesmo: um script Python mestre que gera o biomodelo
parametrizável de membro superior, executável no Blender.

O caminho mudou:

```text
Claude Code + bridge
  → inspeciona a árvore Biomodelo viva
  → propõe patch incremental
  → executa via execute_code
  → verifica imediatamente (re-leitura via bridge)
  → repete por região
    ↓
  quando região validada:
  → consolida em GN_Biomodel_Source
  → user roda manualmente
  → VB_Biomodel_Generated é atualizado
```

O "agente" nesta fase é Claude Code operado pelo designer.
O painel embarcado no Blender não é necessário para esta fase de construção.

### Artefatos

| Artefato | Papel |
|---|---|
| `Biomodelo` | árvore viva — ambiente de desenvolvimento |
| `smoke_bridge.py` | validação do ciclo mínimo — CONCLUÍDO |
| `blender_connection.py` | cliente bridge para Claude Code |
| `GN_Biomodel_Source` | source consolidado — escrito quando seção está pronta |
| `VB_Biomodel_Generated` | gerado pelo source, descartável |
| `docs/CURRENT_TREE_BIOMODEL_INVENTORY.md` | inventário extraído da árvore atual |

---

## 2. Caminhos disponíveis

| Caminho | Status | Fonte da verdade | Usar quando |
|---|---|---|---|
| Patches incrementais via bridge | **primário** | árvore viva `Biomodelo` | construindo/evoluindo o biomodelo |
| `GN_Biomodel_Source` workflow | consolidação | source script completo | seção validada, pronta para serializar |
| `GN_Agent_Draft` mutation workflow | legado | árvore viva + draft | usuário pede patch via painel embarcado |

---

## 3. Convenção de patch incremental

Cada patch é um script Python enviado via `execute_code` pelo canal direto do bridge.

Estrutura obrigatória:

```python
# PATCH: descrição em uma linha
# ALVO: NomeDaÁrvore / NomeDoNó
# RISCO: baixo | médio | alto
import bpy

TREE_NAME = "Biomodelo"
NODE_NAME = "NomeDoNó"

tree = bpy.data.node_groups.get(TREE_NAME)
assert tree is not None, f"FAIL: árvore '{TREE_NAME}' não encontrada"

node = tree.nodes.get(NODE_NAME)
assert node is not None, f"FAIL: nó '{NODE_NAME}' não encontrado"

# Estado anterior
antes = node.inputs[0].default_value
print(f"ANTES: {antes}")

# Mutação (uma alteração)
node.inputs[0].default_value = novo_valor

# Verificação
depois = node.inputs[0].default_value
print(f"DEPOIS: {depois}")
print("OK" if depois == novo_valor else f"FAIL: esperado {novo_valor}, obtido {depois}")
```

Após cada patch: `get_node_context` confirma que a mudança está persistida.

---

## 4. Três camadas (perspectiva futura — em espera)

O plano original de três camadas continua válido como direção de longo prazo,
mas não está em andamento agora. Registrado aqui para referência futura.

### Camada 1: DSL do biomodelo

Vocabulário de domínio estável (parâmetros, regiões, segmentos, poses, joins).
Só promover padrões ao DSL depois de úteis e testados.

### Camada 2: backend de authoring de nós

Opções: raw `bpy` (padrão atual) ou `nodebpy` (experimental, decisão adiada).

Decisão vigente sobre `nodebpy`:
- Requer Python `>=3.13`
- GPL-3.0-or-later
- Compatibilidade com Blender bundled Python não verificada
- Não é dependência do addon até decisão explícita

### Camada 3: escape hatch

Raw `bpy` direto para exploração e casos não cobertos pelo helper layer.
Quando um padrão raw se repete, promover para helpers.

---

## 5. Regras de decisão

### Quando usar patches incrementais

- Ao construir ou evoluir a árvore `Biomodelo`.
- Ao explorar como implementar um comportamento novo.
- Sempre que o resultado precisar ser verificado imediatamente.

### Quando consolidar em source

- Quando uma região da árvore está visualmente validada e os parâmetros estáveis.
- Quando queremos um artefato reproduzível de uma seção pronta.
- Quando o designer pede explicitamente o script mestre de uma região.

### Quando usar legado draft mutation

- Quando o usuário pede explicitamente para patchear uma árvore via painel embarcado.
- Nunca como caminho padrão de construção do biomodelo nesta fase.

### Quando mutar `Biomodelo` diretamente

- Sempre — é a árvore de desenvolvimento nesta fase.
- Patches incrementais operam diretamente sobre ela.
- Snapshots em marcos protegem contra erros grandes.

### Quando usar `VB_Biomodel_Generated`

- Apenas quando `GN_Biomodel_Source` for rodado manualmente.
- É output descartável — pode ser recriado a qualquer momento.

---

## 6. Fases de trabalho (atualizadas)

### Fase 0: ciclo mínimo de pilotagem — CONCLUÍDO (2026-06-10)

Implementado e validado:
- `list_tree_nodes` e `find_tree_nodes` registrados no canal direto `HANDLERS`.
- 3 métodos de conveniência adicionados a `BlenderConnection`.
- `smoke_bridge.py` criado: 5/5 passos OK (ping, inventário, inspeção, noop, patch real).

### Fase 1: inspeção e mapeamento por região — PRÓXIMO

Objetivo: entender a estrutura da `Biomodelo` antes de propor patches de evolução.

Tarefas:
1. Listar todos os frames e seus nós filhos.
2. Para cada região: identificar tipo de nós, inputs numéricos, conexões.
3. Priorizar a primeira região para evoluir (candidato: Antebraço).

### Fase 2: patches incrementais por região

Objetivo: evoluir a árvore viva região por região.

Entrar nesta fase quando: mapa da Fase 1 estiver pronto para ao menos uma região.

### Fase 3: consolidação em source

Objetivo: serializar regiões validadas em `GN_Biomodel_Source`.

Entrar nesta fase quando: ao menos uma região estiver visualmente validada no Blender.

### Fases em espera (plano original preservado)

As fases abaixo do plano de 2026-06-03 (Phase 2: source-mode isolation, Phase 3: helper layer,
Phase 4: parity, Phase 5: nodebpy) continuam como direção de longo prazo.
Não estão em andamento. Serão revisitadas após a Fase 2 incremental estar funcionando.

---

## 7. O que fazemos agora

```text
Próximo passo: mapear a árvore Biomodelo por região via bridge,
escolher a primeira região e executar o primeiro patch real de construção.
```

**Não fazer agora:**
- Não implementar o handler `biomodel_source.py` dedicado.
- Não refatorar `handler/workspace.py` para remover o shortcut de seed.
- Não escrever `GN_Biomodel_Source` completo antes de ter seções prontas.
- Não introduzir `nodebpy` como dependência.
- Não trabalhar no agente embarcado (router, session stores, UI chat).
