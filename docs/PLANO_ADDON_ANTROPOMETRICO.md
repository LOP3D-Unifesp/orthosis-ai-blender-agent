# Plano do Addon Antropométrico — Biomodelo Paramétrico

> **Status:** spec de análise (2026-06-13). Nenhuma alteração feita na árvore de nós.
> **Objetivo deste doc:** servir de ponto de partida para uma nova sessão de implementação.
> **Origem:** análise do projeto `simulador-mao3d-main` (React/Three.js, desenvolvido pela sócia)
> cruzada com os 41 parâmetros atuais do biomodelo Blender.

---

## 0. Resumo executivo

O biomodelo hoje tem **41 parâmetros soltos** (mistura tamanho e pose, ordem confusa,
muita medida que poderia ser estimada). O simulador da sócia resolve isso derivando a mão
**inteira** de 3 entradas (sexo, percentil, idade) via tabelas de proporção antropométrica.

**Meta do produto:** um addon Blender onde o clínico:
1. escolhe **percentil + sexo + idade** → gera um biomodelo de tamanho plausível;
2. **refina tamanhos** por região (campos pré-preenchidos pela estimativa, editáveis);
3. aplica **posicionamento padrão** (poses clínicas mapeadas) com ajuste fino;
4. tudo ancorado num **preset de referência** = os valores atuais que reproduzem o scan real.

Redução esperada da interface: **41 → ~12 controles primários** (+ overrides avançados).

---

## PARTE 1 — Análise do simulador da sócia

### 1.1. A arquitetura de derivação

Fluxo (em `src/utils/anthropometry/profile.js`):

```
buildProfile(sexo, percentil, idade)  →  escalas (palmScale, fingerScale, thumbScale)
makeDims(profile)                     →  TODAS as dimensões (palma, dedos, polegar, punho, antebraço)
```

Tudo parte de **um comprimento de palma de referência** (`PALM_DIMS.LENGTH = 70 mm`)
multiplicado por escalas, e o resto sai de **ratios fixos**.

### 1.2. Escalas globais (`buildProfile`)

| | palmScale | fingerScale | thumbScale |
|---|---|---|---|
| Masculino | 1.05 | 1.03 | 1.03 |
| Feminino | 0.97 | 0.98 | 0.98 |

Multiplicadas por `sc = interpPercentileScale(percentil) × ageScale(idade)`:

- **Percentil** (clamp 5–95): P5 → 0.92 · P50 → 1.00 · P95 → 1.08 (linear nos dois trechos).
- **Idade** (clamp 5–90): linear por pontos — `[5,0.6] [10,0.78] [14,0.9] [18,1.0] [65,1.0] [80,0.98] [90,0.96]`.

### 1.3. Ratios de proporção (`src/constants/anthropometry.js`)

**Comprimentos de falange** (`PHAL_RATIOS`) — fração do dedo médio (D3), e segmentação interna:

| Dedo | Total (vs D3) | Proximal | Média | Distal |
|---|---|---|---|---|
| D2 indicador | 0.882 | 0.510 | 0.287 | 0.203 |
| D3 médio | 1.000 | 0.505 | 0.298 | 0.197 |
| D4 anelar | 0.954 | 0.491 | 0.304 | 0.205 |
| D5 mínimo | 0.756 | 0.490 | 0.271 | 0.239 |
| Polegar | 0.660 | 0.593 (prox) | — | 0.407 (dist) |

`d3Total = d3ToPalm × palmLen × fingerScale` (d3ToPalm = 1.03 M / 0.99 F).

**Espessuras** (`RATIOS`) — fração da espessura da palma (`palmThick`):

```
fingerWidths = [10/14, 9/14, 8/14]   → prox, média, distal
thumbWidths  = [10/14, 9/14]         → prox, distal
```

**Posições laterais das bases dos dedos** (`RATIOS.baseZ`, × palmWidth):
`[18/55, 6/55, -6/55, -18/55]` (D2 → D5).

**Coxim de ponta** (`TIP_SOFT_MM`, escala com palmLen/70): D2 3.84 · D3 3.95 · D4 3.95 · D5 3.73 · Polegar 5.67 mm.

**Cadeia palma → punho → antebraço** (`SEX_RATIOS`):

| Ratio | Masculino | Feminino | Significado |
|---|---|---|---|
| palmWidthToLength | 0.80 | 0.82 | largura = comprimento × isto |
| palmThickToWidth | 0.27 | 0.25 | espessura = largura × isto |
| wristRadToPalmWidth | 0.30 | 0.29 | raio punho = largura palma × isto |
| wristLenToPalmThick | 1.10 | 1.05 | comprimento punho |
| forearmLenToPalmLen | 1.75 | 1.70 | comprimento antebraço |
| forearmProxToWrist | 1.15 | 1.10 | raio cotovelo = raioPunho × isto |
| forearmDistToWrist | 0.90 | 0.88 | raio distal antebraço |
| d3ToPalm | 1.03 | 0.99 | dedo médio total |
| thumbBaseFromProx | 0.21 | 0.19 | posição base do polegar |

### 1.4. Pose: controles conjuntos

- **Global D2-D5** (`GlobalD2D5Panel.jsx`): um único MCP/PIP/DIP aplicado aos 4 dedos.
- **DIP acoplado**: `DIP = 0.6 × PIP` (tendão flexor compartilhado — clinicamente realista).
  Em `defaults.js`: `DIP: Math.round(0.6 * pip)`.
- **Grip 0-100** (`computeGrip.js`): um slider de fechamento interpola entre poses
  open/mid/closed da mão toda (dedos + polegar + punho), via keyframes funcionais.

### 1.5. Pose: ranges clínicos (`src/constants/biomechanics.js`)

```
Dedos:   MCP [-45, 90]   PIP [0, 100]   DIP [-20, 80]
Polegar: CMC_ABD [-15, 70]   CMC_FLEX [-70, 15]   MCP [0, 60]   IP [-10, 80]
Punho:   flex/ext [-70, 80]   desvio rad/ulnar [-20, 30]
```

> Divergem dos ranges atuais do biomodelo (que usa −20..110 genérico). Reconciliar na implementação.

### 1.6. Oposição do polegar (movimento que o biomodelo NÃO tem)

O simulador modela oposição como **1 comando clínico** → 3 rotações do rig, via matriz de acoplamento
(`THUMB_CMC.OPP_COUPLING`):

```
θ_abd  = u_abd  + 0.18 × u_opp
θ_flex = u_flex + 0.22 × u_opp
θ_pron =          0.38 × u_opp
```

Escala **Kapandji 0-10** (`kapandji.js`) mapeia teste clínico → comando de oposição:
`{0:-20, 1:-10, 2:0, 3:8, 4:16, 5:24, 6:34, 7:45, 8:55, 9:63, 10:70}`.

Fundamentação em `docs/CMC_BIOMECANICA_MODELO.md` (refs: Hollister 1992, Crisco 2015, Kapandji 1986).

---

## PARTE 2 — Definição do produto (addon)

### 2.1. Fluxo de uso

```
[1] Antropometria base        → percentil + sexo + idade  → "Criar/Atualizar Biomodelo"
[2] Tamanho refinado          → campos por região, pré-preenchidos pela estimativa, editáveis
[3] Pose                       → poses padrão (funcional/neutro/zero) + sliders conjuntos + ajuste fino
[4] Presets de referência      → "Scan Luiz" e outros; salvar/carregar conjunto completo de valores
```

### 2.2. Camadas de controle (do grosso ao fino)

| Camada | Controles | Origem |
|---|---|---|
| **Antropometria** | sexo, percentil, idade | entrada direta |
| **Tamanho** | comprimento da palma (âncora) + overrides por segmento | estimado, editável |
| **Pose global** | MCP, PIP dedos (DIP acoplado); grip opcional | entrada direta |
| **Pose fina** | flex por dedo, abdução por dedo, polegar, punho | override |
| **Polegar avançado** | oposição (Kapandji), pronação | entrada direta (novo) |

### 2.3. Decisões de design a fechar (antes de implementar)

1. **Onde vivem os ratios?**
   - **Opção A — no addon (Python):** o addon calcula os 41 valores e escreve nos sockets do modifier.
     Tree fica como está. Override = editar o valor depois. *Casa perfeitamente com "pré-preenchido e editável".* **(recomendada para começar)**
   - **Opção B — na árvore (Geometry Nodes):** math nodes calculam tamanhos a partir de ~3 inputs.
     Árvore autossuficiente sem addon, porém mais nós e refator pesado. (futuro)
   - Recomendação: **A** agora, manter **B** como evolução possível.

2. **2 cadeias vs 4 dedos.** O biomodelo agrupa em 2 cadeias (Dedo 1 = indicador+médio radial,
   Dedo 2 = anelar+mínimo ulnar); o simulador tem D2–D5 separados. Definir o mapeamento de
   agregação (ex.: cadeia 1 ← média D2/D3; cadeia 2 ← média D4/D5).

3. **Calibração dos ratios ao scan.** Os ratios do simulador são ponto de partida genérico.
   Será preciso calibrá-los para que a estimativa reproduza o **scan de referência** (Apêndice A) —
   provavelmente fixando o scan como um percentil/sexo específico e ajustando ratios divergentes.

4. **Acoplamentos como toggle.** DIP=0.6×PIP e global-vs-por-dedo devem ser ligáveis/desligáveis
   na UI (override clínico para rigidez/deformidade).

5. **Oposição do polegar** exige mudança na árvore (novo movimento) — agendar como etapa própria.

6. **Unidades.** Distâncias em mm; ângulos em graus diretos (já corrigido na árvore).

---

## PARTE 3 — Mapeamento dos 41 parâmetros atuais

Legenda: **DERIVAR** = vira valor calculado (editável como override) · **POSE** = controle de pose
mantido · **NOVO** = a adicionar · âncora = entrada de tamanho primária.

### Antebraço
| Param atual | Destino | Fórmula / nota |
|---|---|---|
| Comp Antebraço | DERIVAR | `palmLen × forearmLenToPalmLen` |
| Raio Cotovelo | DERIVAR | `raioPunho × forearmProxToWrist` |
| Raio Punho | DERIVAR | `palmWidth × wristRadToPalmWidth` |
| Desvio Rad/Ulnar Punho | POSE | range clínico [-20, 30] |
| Flex/Ext Punho | POSE | range clínico [-70, 80] |

### Palma
| Param atual | Destino | Fórmula / nota |
|---|---|---|
| Comp Metacarpo | **ÂNCORA** | comprimento da palma — entrada de tamanho primária |
| Largura Metacarpo | DERIVAR | `palmLen × palmWidthToLength` |
| Espessura Metacarpo | DERIVAR | `palmWidth × palmThickToWidth` |
| Curva Palma Metacarpo 1 | POSE/forma | não há no simulador; manter |
| Curva Palma Metacarpo 2 | POSE/forma | idem |

### Polegar
| Param atual | Destino | Fórmula / nota |
|---|---|---|
| Comp Metacarpo Polegar | DERIVAR | relacionar a thumbBase/palma (calibrar) |
| Largura Metacarpo Polegar | DERIVAR | `thumbWidths[0] × palmThick` |
| Espessura Metacarpo Polegar | DERIVAR | `thumbWidths[0] × palmThick` (calibrar p/ espessura) |
| Comp Falange Prox Polegar | DERIVAR | `thumbTotal × 0.593` |
| Espessura Falange Prox Polegar | DERIVAR | `thumbWidths[0] × palmThick` |
| Comp Falange Dist Polegar | DERIVAR | `thumbTotal × 0.407` |
| Espessura Falange Dist Polegar | DERIVAR | `thumbWidths[1] × palmThick` |
| Flex/Ext Polegar | POSE | CMC flexão, range [-70, 15] |
| Abdução Polegar | POSE | CMC abdução, range [-15, 70] |
| Flex/Ext Falange Prox Polegar | POSE | MCP polegar, range [0, 60] |
| Flex/Ext Falange Dist Polegar | POSE | IP polegar, range [-10, 80] |
| — | **NOVO** | Oposição (Kapandji 0-10) + acoplamento |

`thumbTotal = d3Total × 0.66 × (thumbScale / fingerScale)`.

### Dedos 1 e 2 (idêntico para as duas cadeias)
| Param atual (×2) | Destino | Fórmula / nota |
|---|---|---|
| Comp Falange Prox 1/2 | DERIVAR | `dedoTotal × seg.pp` |
| Comp Falange Media 1/2 | DERIVAR | `dedoTotal × seg.pm` |
| Comp Falange Dist 1/2 | DERIVAR | `dedoTotal × seg.pd` |
| Espessura Falange Prox 1/2 | DERIVAR | `fingerWidths[0] × palmThick` |
| Espessura Falange Media 1/2 | DERIVAR | `fingerWidths[1] × palmThick` |
| Espessura Falange Dist 1/2 | DERIVAR | `fingerWidths[2] × palmThick` |
| Flex/Ext Falange Prox 1/2 | POSE → **global MCP** | compartilhado entre cadeias |
| Flex/Ext Falange Media 1/2 | POSE → **global PIP** | compartilhado entre cadeias |
| Flex/Ext Falange Dist 1/2 | DERIVAR | `0.6 × PIP` (override possível) |
| Abdução Dedo 1/2 | POSE | leque/spread por cadeia |

### Contagem final
- **POSE primários:** wrist flex, wrist dev, palm curve 1, palm curve 2, thumb flex, thumb abd,
  thumb MCP, thumb IP, abd dedo 1, abd dedo 2, global MCP, global PIP → **12**
- **NOVO:** oposição do polegar → **+1**
- **TAMANHO primário:** sexo, percentil, idade, comp palma (âncora) → **4** (geram os ~22 derivados)
- **Derivados/override:** ~22 campos, escondidos em painel "Avançado", pré-preenchidos.

---

## PARTE 4 — Plano de implementação em etapas

### Etapa 0 — Salvaguardas (fazer primeiro, antes de qualquer mudança) — CONCLUÍDA (2026-06-13)
- [x] Capturar os 41 valores **vivos** da árvore `Biomodelo` via bridge e salvar como preset
      `presets/scan_referencia.json` (a "verdade do scan"). Capturado do objeto `devbiomodelo.001`
      (modifier `GeometryNodes`) em `testeAgenteBlender1.blend`. Scripts reprodutíveis:
      `runtime/capture_scan_referencia.py` + `runtime/build_scan_preset.py`.
- [x] Snapshot `.blend` do estado atual: `runtime/snapshots/addon_antropometrico_etapa0_20260613T154658Z/pre_addon_antropometrico.blend` (cópia; arquivo ativo intacto).
- [x] Garantir que o source instancia o objeto na cena (feito nesta sessão em `GN_Biomodel_Source_v1.py`).

### Etapa 1 — Camada antropométrica (cálculo puro, sem Blender) — CONCLUÍDA (2026-06-13, calibração adiada)
- [x] Portar `buildProfile` + `makeDims` para Python (módulo `blender_addon/biomodel/anthropometry.py`). Porte fiel, sem `bpy`.
- [x] Tabela de ratios como constantes (espelho de `anthropometry.js`), em mm e adaptada às 2 cadeias (cadeia 1 ← média D2/D3, cadeia 2 ← média D4/D5).
- [x] Função `derive_params(sexo, percentil, idade, comp_palma=None) → {identifier: valor}` — 25 sockets de tamanho; `comp_palma` escala a mão uniformemente. POSE classificada à parte (`POSE_SOCKETS`).
- [~] **Calibrar** ratios contra o scan — **ADIADO** (decisão do usuário: automações primeiro). Em vez disso, ferramenta de diagnóstico `runtime/diagnose_anthropometry.py` expõe os deltas; achados em `docs/ETAPA1_DIAGNOSTICO_ANTROPOMETRIA.md` (|Δ%| médio ~38%, padrão claro: semântica da âncora + palma "grossa/estreita").
- [x] Testes unitários (sem Blender): `tests/test_anthropometry.py` — 16 testes, 16 passam.

### Etapa 2 — Mapeamento e redução da interface
- [ ] Fechar as decisões de design da seção 2.3.
- [ ] Documentar o conjunto final de sockets (primários vs derivados/override).
- [ ] Reordenar painéis da interface GN: Antropometria → Tamanho → Pose → Avançado.
- [ ] Implementar acoplamentos (DIP=0.6×PIP, global MCP/PIP) — via nós ou via addon.

### Etapa 3 — Addon: geração e UI — CONCLUÍDA (2026-06-13)
- [x] Operator `biomodel.create_object` — cria objeto novo com modifier → árvore `Biomodelo` (não clobbera `Biomodelo_Edu`/scan).
- [x] Painel `BIOMODEL_PT_Anthropometry` (View3D > Sidebar > **Biomodelo**) com sexo/percentil/idade (+override comp. de palma) → `biomodel.apply_anthropometry` escreve os 25 sockets de tamanho no modifier ativo. Não altera a árvore (só `modifier[identifier]`).
- [x] Override fino de tamanho: os 25 sockets são do modifier → editáveis no painel padrão de Modifier após "Aplicar".
- [x] Botões de preset: `load_scan_reference` (acha `presets/scan_referencia.json` via project root ou pasta do .blend) + `save_preset`/`load_preset` (file browser, formato schema 1.0, 41 valores).

**Arquivos:** `blender_addon/biomodel/presets.py` (I/O puro), `blender_addon/ui/anthropometry_panel.py` (props+ops+panel), registro em `ui/__init__.py`, bl_info 0.5.0.
**Validação via bridge (sem restart):** objeto temporário reproduz o pipeline — 25 sockets aplicados, geometria escala com a âncora (P50→Y128.6, ancorado 78.62→Y137.6, P95@120→Y210.0), topologia preservada (634 verts), `Biomodelo_Edu` intacto. Registro/unregistro limpos; 5 operadores presentes; `preset_ids=41`.
**Deploy:** addon instalado é CÓPIA do repo (`%APPDATA%\...\scripts\addons\blender_addon`). Arquivos copiados (+`.bak` dos sobrescritos). **Falta o usuário reiniciar o Blender** (ou reativar o addon) para a aba "Biomodelo" aparecer. Achado durante o deploy: `source_template.py` instalado estava defasado (39 params, sem `Socket_76/77`) — também redeployado.

### Etapa 4 — Pose: controles conjuntos + oposição do polegar
- [ ] Global D2-D5 e DIP acoplado funcionando ponta a ponta.
- [ ] Grip 0-100 (opcional, keyframes funcionais).
- [ ] Adicionar oposição do polegar à árvore (matriz de acoplamento + Kapandji) — mudança de árvore.
- [ ] Aplicar ranges clínicos da seção 1.5.

### Etapa 5 — Consolidação
- [ ] Atualizar `GN_Biomodel_Source` com a estrutura nova.
- [ ] Regressão: versão simplificada reproduz o scan de referência (Apêndice A) dentro da tolerância.
- [ ] Atualizar `CLAUDE.md` e memórias.

---

## Apêndice A — Scan de referência (valores atuais que reproduzem o scan real)

Defaults consolidados em `biomodel_source/GN_Biomodel_Source_v1.py` (snapshot da árvore viva em 2026-06-12).
**Antes de implementar, recapturar da árvore viva via bridge** — esta tabela pode estar defasada.

**Antebraço:** Comp 230.2 · Raio Cotovelo 37.3 · Raio Punho 24.93 · Desvio Punho −5.37 · Flex/Ext Punho 0.0

**Palma:** Comp Metacarpo 78.62 · Largura 35.74 · Espessura 29.5 · Curva 1 0.0 · Curva 2 0.0

**Polegar:** Comp MC 48.74 · Larg MC 26.37 · Esp MC 25.94 · Flex/Ext 0.0 · Abdução 15.0 ·
Flex Prox 4.72 · Flex Dist −17.82 · Comp Prox 27.8 · Esp Prox 26.11 · Comp Dist 20.53 · Esp Dist 21.66

**Dedo 1 (indicador+médio):** Abdução 26.99 · Flex Prox/Media/Dist 0/0/0 ·
Comp Prox 53.04 · Esp Prox 25.0 · Comp Media 23.99 · Esp Media 22.0 · Comp Dist 30.31 · Esp Dist 15.6

**Dedo 2 (anelar+mínimo):** Abdução 11.82 · Flex Prox/Media/Dist 0/0/0 ·
Comp Prox 62.51 · Esp Prox 24.71 · Comp Media 23.07 · Esp Media 19.23 · Comp Dist 32.89 · Esp Dist 21.85

---

## Apêndice B — Arquivos-fonte do simulador (referência)

| Arquivo | Conteúdo |
|---|---|
| `src/constants/anthropometry.js` | PHAL_RATIOS, RATIOS, SEX_RATIOS, TIP_SOFT_MM, PALM_DIMS |
| `src/utils/anthropometry/profile.js` | buildProfile, makeDims, interpPercentileScale, ageScale |
| `src/constants/biomechanics.js` | RANGES, OPP_COUPLING do polegar |
| `src/constants/gripKeyframes.js` + `src/utils/grip/computeGrip.js` | grip 0-100 |
| `src/components/GlobalD2D5Panel.jsx` | controle global dos dedos |
| `src/utils/pose/defaults.js` | DIP=0.6×PIP, poses neutras |
| `src/constants/kapandji.js` | escala Kapandji → comando oposição |
| `docs/CMC_BIOMECANICA_MODELO.md` | formalização matemática + refs PubMed |

---

## Apêndice C — Arquivos do biomodelo Blender afetados

| Arquivo | Papel |
|---|---|
| `blender_addon/biomodel/source_template.py` | PARAMETERS canônicos (atualizar com nova estrutura) |
| `biomodel_source/GN_Biomodel_Source_v1.py` | source consolidado (regenerar na Etapa 5) |
| `blender_addon/biomodel/anthropometry.py` | **novo** — camada de derivação (Etapa 1) |
| `blender_addon/ui/` | **novo** — painel do addon (Etapa 3) |
