# Ecossistema Limbse — Contexto para o Projeto Blender

## Visão geral

A Limbse é uma startup de tecnologia assistiva incubada no In.cube InovaHC/USP.
O produto principal é a NeurovIvA — sistema integrado de reabilitação composto por:

1. **Órtese 3D personalizada** — escaneamento, design paramétrico, impressão
2. **Plataforma de prescrição** — profissionais prescrevem e acompanham remotamente
3. **App de telereabilitação** — exercícios, monitoramento, teleatendimento

O projeto Blender + IA é a camada de **fabricação** desse ecossistema.

---

## Repos relevantes

### simulador-mao3d
Simulador biomecânico 3D de mão para profissionais da saúde.
React + Three.js. Já em produção parcial.

**O que já está implementado e é diretamente útil:**

`buildProfile(sexo, percentil, idade)` — gera perfil antropométrico
`makeDims(profile)` — retorna todas as dimensões da mão:
- `palm` — comprimento, largura, espessura
- `fingers[]` — comprimento de cada falange por dedo (D2-D5)
- `thumbLen[]` — falanges do polegar
- `thumbBase` — posição 3D da base do polegar (x, y, z)
- `forearm` — comprimento, raios proximal e distal
- `wrist` — raio e comprimento
- `neutralFingers` — ângulos neutros por dedo (MCP, PIP, DIP em radianos)
- `neutralThumb` — ângulos neutros CMC (abd, flex, opp)

**Modelo biomecânico da CMC do polegar:**
Converte ângulos clínicos → rotações 3D com acoplamento validado:
- `u_abd` (abduçao/adução CMC)
- `u_flex` (flexão/extensão CMC)
- `u_opp` (oposição/retroposição)

Baseado em literatura científica (Hollister 1992, Halilaj 2014, Crisco 2015).

**Parâmetros clínicos completos já definidos:**
- Sexo, percentil, idade
- Ângulos CMC polegar (abd / flex / opp)
- MCP, PIP, DIP por dedo (D2-D5)
- Flexão e desvio do punho
- Kapandji (oposição)

**Como usar no Blender:**
Exportar output de `makeDims()` como JSON → consumir no Geo Nodes como
parâmetros de entrada. Elimina necessidade de inserção manual de medidas.

---

### automation_creation_orthotics (Unifesp / LOP3D)
Addon Blender para automação da criação de órteses.
Acesso para colaboração disponível.

**O que já está implementado:**
- Decimação de malha (Collapse, Un-Subdivide, Planar)
- Alinhamento por eixo (X, Y, Z)
- Criação de bones a partir de posições
- Interface organizada (Inicialização / Preparar modelo / Roadmap)
- Assets: `ScanMaoEspastica.stl`, `ScanMaoEspastica_2.stl`, `template.blend`

**Roadmap deles:**
1. Landmarks anatômicos
2. Rigging
3. Reposicionamento anatômico

**Divisão de responsabilidades sugerida:**
- Addon Unifesp → preparação do biomodelo (importar STL, decimar, alinhar)
- Nosso addon → geração paramétrica da órtese via Geo Nodes

Evitar reimplementar o que eles já resolveram.

---

## Pipeline completo do ecossistema

```
Formulário de prescrição (Limbse / Figma)
        ↓ parâmetros clínicos
simulador-mao3d
        ↓ buildProfile() + makeDims() → JSON
Blender (nosso addon + addon Unifesp)
        ↓ biomodelo de referência + Geo Nodes paramétrico
Órtese 3D (malha para impressão)
        ↓
Impressão 3D
        ↓
Órtese física para o paciente
```

---

## Lacunas que ainda existem

**Formulário → simulador:** o formulário ainda está no Figma.
Quando for implementado, os parâmetros devem vir estruturados em JSON
compatível com `buildProfile()` + `makeDims()`.

**Simulador → Blender:** o simulador ainda não exporta nada.
Criar um endpoint ou exportador JSON é o próximo passo de integração.
Por enquanto: inserção manual dos parâmetros no Blender.

**Addon Unifesp → nosso addon:** ainda são projetos separados.
A colaboração pode começar com reuso dos operadores de decimação e
alinhamento, sem necessidade de unificar os addons imediatamente.
