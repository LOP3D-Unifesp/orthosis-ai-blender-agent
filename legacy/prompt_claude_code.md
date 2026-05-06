# Prompt — Claude Code: Sistema de Geo Nodes para Órtese de Membro Superior

> Este prompt é entregue ao Claude Code quando a arquitetura do sistema estiver
> definida e validada manualmente. Ele assume que os padrões de nós já foram
> testados no Blender e documentados em `rules/`.

---

## Contexto

Você vai implementar um sistema de Geometry Nodes no Blender que gera
parametricamente a geometria de uma órtese de membro superior.

O projeto já tem:
- Um arquivo `.blend` base (`geonode ort v2.blend`) com o node tree inicial
- Padrões de nó validados (ver `rules/geonodes_node_reference.md`)
- Um padrão G1 para junções suaves entre Bézier Segments (ver `rules/padrao_g1_tres_handlers.md`)
- Conexão MCP com o Blender via `blender-orthosis` na porta 65432
- Um inspector de cena (`blender_scene_inspector.py`) que exporta o estado atual

## O que você vai construir

### Fase 1 — Curvas (esqueleto)

Completar o node group `Geometry Nodes.001` com:

1. **Expor parâmetros anatômicos** como inputs do grupo:
   - `Ponto de Junção` (Vector) — junção antebraço/mão
   - `Handle Final Antebraço` (Vector) — tangente de chegada na junção
   - `End Mão` (Vector) — ponto final do caminho da mão
   - `Handle Final Mão` (Vector) — tangente de chegada na mão
   - `Tensão G1` (Float, 0–2, default 1.0) — controle da suavidade na junção

2. **Caminho do polegar** — segundo Bézier encadeado a partir de `Vec_Ponto_Juncao`,
   com continuidade G1 aplicada pelo mesmo padrão já implementado.
   Adicionar os nós: `Vec_Ponto_Polegar`, `Vec_Handle_Polegar`,
   e a cadeia `VM_G1_Subtract_P / VM_G1_Scale_P / VM_G1_Add_P`.

3. **Conectar perfil ao Curve to Mesh**:
   - Adicionar nó `Curve to Mesh`
   - Conectar `Bezier Segment` (Caminho Geral) → `Curve to Mesh.Curve`
   - Conectar `Bézier Segment` (perfil) → `Curve to Mesh.Profile Curve`
   - Substituir a saída de `Transform Geometry` por `Curve to Mesh` no `Join Geometry`

### Fase 2 — Malha bruta (lofting)

Implementar o lofting entre perfis:

1. Para cada seção (antebraço, punho, mão): criar um Bézier Segment de perfil
2. Usar `Sample Curve` no caminho principal para posicionar cada perfil
3. Interpolar a forma dos perfis ao longo do caminho (forma em U → forma de mão)
4. Gerar a superfície via `Curve to Mesh` com perfil variável

### Fase 3 — Furos de ventilação

Parâmetros controláveis pelo operador:
- Forma (Voronoi / grid / custom)
- Tamanho
- Densidade / espaçamento
- Distância mínima da borda (os furos nunca tocam a borda)

### Fase 4 — Espessura

- Adicionar `Solidify` / equivalente em GN no final da cadeia
- Parâmetro: espessura em mm

---

## Parâmetros do grupo (estado final esperado)

```python
inputs = [
    ("Geometry",              "NodeSocketGeometry"),
    ("Largura B.A.",          "NodeSocketFloat"),      # mm
    ("Extensão Antebraço",    "NodeSocketVector"),     # direção + comprimento
    ("Ponto de Junção",       "NodeSocketVector"),     # posição 3D
    ("Handle Final Antebraço","NodeSocketVector"),     # tangente
    ("End Mão",               "NodeSocketVector"),     # posição 3D
    ("Handle Final Mão",      "NodeSocketVector"),     # tangente
    ("Tensão G1",             "NodeSocketFloat"),      # 0.0–2.0
    ("Espessura",             "NodeSocketFloat"),      # mm, fase 4
]
```

---

## Como operar o Blender

Use as ferramentas MCP disponíveis:

```python
# Ler estado atual antes de qualquer modificação
get_scene_summary()
get_tree_structure(tree_name="Geometry Nodes.001")

# Conectar nós
connect_nodes(from_node, from_socket, to_node, to_socket, tree_name)

# Desconectar
disconnect_nodes(from_node, from_socket, to_node, to_socket, tree_name)

# Escrever código Python diretamente (quando as ferramentas não bastam)
enable_mcp_writes()
execute_blender_code(code)
```

**Sempre ler o estado atual antes de modificar.**
**Sempre confirmar com o usuário antes de operações que alteram a estrutura do grupo.**

---

## Regras de desenvolvimento

1. Resolver sempre inputs do grupo **por nome**, nunca por identificador hardcoded
2. Após qualquer `mod[ident] = value`, chamar `obj.data.update_tag()` + `bpy.context.view_layer.update()`
3. O primeiro input de `VM_G1_Subtract` (e variantes) deve ficar **desconectado** — ver `padrao_g1_tres_handlers.md`
4. Trabalhar **sem espessura** até a Fase 4
5. A cada Fase concluída: rodar `blender_scene_inspector.py` e atualizar `scene_snapshot.md`

---

## Fonte dos parâmetros anatômicos

Os valores numéricos NÃO são inventados — vêm do `simulador-mao3d`:

```python
from simulador_mao3d import buildProfile, makeDims

dims = makeDims(buildProfile(sexo="M", percentil=50, idade=30))
# dims contém: largura_punho, comprimento_antebraco, pos_base_polegar, etc.
```

Quando implementar a Fase 1, consumir `dims` como fonte dos vetores de posição.

---

## Entregáveis esperados

Para cada fase:
- Script Python executável no Blender Text Editor OU operações via MCP
- `scene_snapshot.md` atualizado após a fase
- Atualização de `geonodes_node_reference.md` se novos nós foram adicionados
