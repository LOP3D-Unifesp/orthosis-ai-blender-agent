# Consolidação do Biomodelo — 2026-06-12

> `Biomodelo` passa a ser a árvore **canônica** do projeto. Executado direto sobre a árvore viva via bridge, com backup prévio.

## Backup / reversão

| Artefato | Onde |
|---|---|
| `.blend` pré-consolidação | `runtime/snapshots/consolidation_20260612T034627Z/pre_consolidation.blend` |
| Duplicata da árvore (fake_user) | node group `Biomodelo_BACKUP_20260612T034627Z` |

Para reverter: abrir o `.blend` de snapshot, ou trocar o modifier do objeto `devbiomodelo.001` de volta para `Biomodelo_BACKUP_...`.

## 1. Cinemática dos dedos (corrigida)

**Antes:** cada falange era um `GeometryNodeTransform` independente, posicionado para um dedo reto e rotacionado no **eixo Z** (desvio lateral) em torno do centro do cubo. Resultado: a flexão não encurvava e juntas não arrastavam segmentos distais.

**Depois:** forward kinematics matricial por junta, replicando o padrão do polegar de `Geometry Nodes.001`:

```
M0 (MCP) = T(joint0) · Rx(a0)
M1 (PIP) = M0 · T(0,-L0,0) · Rx(a1)
M2 (DIP) = M1 · T(0,-L1,0) · Rx(a2)
cube_n.Transform = M_n · T(offset_lateral, -L_n/2, 0)   # Mode = "Matrix"
```

- Rotação no **eixo X** (flexão anatômica, consistente com punho/polegar).
- `a_n` = `RADIANS(param)` dos sockets de flexão existentes (dedo 1: Socket_47/48/49; dedo 2: Socket_60/61/62).
- Pivô na junta proximal de cada segmento; rotação propaga para os distais.
- Nós novos: prefixo `FK_F1_` (dedo 1) e `FK_F2_` (dedo 2). Reusa `Math_FPxRad`/`CXYZ_FPxRot` (religados de `.Z` para `.X`).

Validação: com flexão 0 a bbox é idêntica ao baseline; com flexão proximal de 50° o Z-min cai de 26.3 → −24.7 (curl fora do plano); pose de punho fechado encurva as duas cadeias em cascata (renders em `runtime/_f1_*.png`, `runtime/_fist_*.png`).

**Convenção de sinal:** valor positivo de flexão = curl para fechar a mão. Inverter = trocar o sinal no `EulerToRotation` (multiplicar o radiano por −1).

## 2. Órtese paramétrica (primeira versão integrada)

Frame `ORTESE v1` (prefixo `ORT_`). Calha (trough) de antebraço:

```
Curve Line (eixo do antebraço) → Set Curve Radius → Curve to Mesh (perfil = Arc em C aberto) → Extrude (espessura) → Join_Geral.002
```

- Ligada às **âncoras reais**: raio do cuff = `Raio Cotovelo` (vivo) + folga; extensão = `Cobertura` × meio-comprimento do antebraço (vivo).
- Params expostos no modifier (interface): `Ortese: Folga (mm)` (Socket_72), `Ortese: Espessura (mm)` (Socket_73), `Ortese: Abertura (graus)` (Socket_74), `Ortese: Cobertura` (Socket_75).
- Unida na saída final, então aparece junto do biomodelo.

Validação: abertura 120° vs 240° muda visivelmente o C (`runtime/_ort_*.png`); render consolidado em `runtime/_final_iso.png`.

## 3. Âncoras semânticas

Frame `ANCORAS` (prefixo `ANC_`), derivadas de params vivos: `ANC_forearm_halflen`, `ANC_forearm_prox`, `ANC_wrist`, `ANC_hand_base` (= −`PontaMC_Base`).

## 4. Harness (repo)

- `blender_addon/tools/handlers.py` — corrigido o **timeout que aplicava mutação após retornar erro** (flag de cancelamento no callback do timer); timeout alinhado (25s main < 30s conn < 60s cliente).
- `blender_addon/tools/execution.py` — `execute_code` retorna `stdout`+`stderr` e, se o patch define `result`, devolve em JSON.
- `blender_addon/tools/validation_tools.py` (novo) — handlers `evaluate_geometry`, `render_viewport`, `set_param`, `resolve_node`, `set_node_input`, `link_sockets`, `add_node`. Registrados em `HANDLERS`. **Ativam no próximo restart do Blender.**
- `blender_connection.py` — removidos métodos mortos (`apply_renames/collections/gn_edits`, `undo`, `runtime_*`); adicionados métodos clientes dos novos handlers.
- `smoke_bridge.py` — força UTF-8 no stdout (fim do erro cp1252 no Windows).

## Adendo — limpeza pós-consolidação (mesma data, sessão posterior)

Por decisão do usuário, o `Biomodelo` voltou a ser **biomodelo puro**:

1. **Órtese v1 descartada.** O protótipo de calha ficou visualmente ruim (tubo estranho dentro do braço). Removidos todos os nós `ORT_*`, `ANC_*` e os sockets `Ortese: Folga/Espessura/Abertura/Cobertura` (Socket_72–75). A seção "2. Órtese paramétrica" e "3. Âncoras semânticas" acima ficam como **registro histórico** — esses nós não existem mais. A órtese será reconstruída num passo próprio a partir das curvas de `Geometry Nodes`.
2. **Bug de unidades da flexão corrigido.** Os sockets de flexão dos dedos (47/48/49, 60/61/62) e das falanges do polegar (38/39) tinham subtype `ANGLE`: a UI mostra graus mas armazena **radianos**, e o nó `RADIANS` da árvore convertia de novo (dupla conversão ÷57.3) — por isso o slider "malemal movia" o dedo. Corrigido para subtype `NONE` (graus diretos, consistente com punho/polegar que já funcionavam) com range −20..110.
3. **Matemática morta purgada**: `Combine XYZ.002–.007` e `Math.007–.028` (28 nós) removidos iterativamente (só nós sem links de saída). `Math.006` (`PontaMC_Base`) preservado — alimenta o FK.

Estado final: **181 nós / 235 links / 0 inválidos**, malha avaliada = 634 vértices (idêntico ao baseline pré-órtese). Punho fechado validado com MCP 85° / PIP 95° / DIP 50° (renders `runtime/_clean_*.png`). Smoke test 5/5. Arquivo salvo.

## Pendências

1. **Órtese: reconstruir do zero** ligada a âncoras do biomodelo, partindo das curvas Bezier de `Geometry Nodes` (obj `luizbiomodelo`) — não reaproveitar o protótipo de calha.
2. Seção da órtese que **acompanha a pose do punho/mão** (imobilização em ângulo).
3. Migrar o **polegar** do `Biomodelo` para o mesmo padrão FK matricial.
4. Re-parametrizar o offset de centro do cubo do FK (hoje constante) caso comprimentos de falange mudem muito.
