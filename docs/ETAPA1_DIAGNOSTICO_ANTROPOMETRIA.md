# Etapa 1 — Diagnóstico: estimativa antropométrica vs scan de referência

> Gerado por `runtime/diagnose_anthropometry.py` (perfil masculino P50, idade 30).
> Compara `derive_params` (tabelas genéricas do simulador) contra
> `presets/scan_referencia.json`. **Nenhuma calibração feita** — este doc é o
> insumo da recalibração futura (decisão: automações antes, calibração depois).

## Resumo

A estimativa genérica diverge **muito** do biomodelo atual (|Δ%| médio ~38–40%),
confirmando que o `Biomodelo` foi montado por referência visual (`Scan_Edu_MaoEspalmada`),
não a partir de proporções antropométricas. Os desvios não são ruído — têm padrão
claro, então a calibração será dirigida, não chute.

## Padrões de divergência (a tratar na calibração)

1. **Semântica da âncora difere.** O `Comp Metacarpo` do biomodelo (78.62 mm) não é o
   "comprimento de palma" do simulador. Evidências:
   - Antebraço biomodelo / palma = 230.2/78.62 = **2.93×**, vs ratio genérico **1.75×** → forearm −40%.
   - Falanges do biomodelo são longas demais p/ essa "palma" (Comp Falange ×2: −44 a −55%).
   - Provável: o `Comp Metacarpo` mede só o bloco metacarpal, não a palma anatômica
     (punho→MCP). **Primeiro passo da calibração:** reconciliar o que a âncora representa.

2. **Seção transversal da palma é "grossa e estreita", não chata.**
   - Largura Metacarpo: biomodelo 35.74 vs genérico 62.9 → estimativa **+76%** (palma genérica é larga).
   - Espessura Metacarpo: biomodelo 29.5 vs genérico 17 → estimativa **−42%** (biomodelo é mais grosso).
   - O "metacarpo" do biomodelo é quase quadrado/profundo; o simulador modela palma chata
     (largura ≫ espessura). Os ratios `palmWidthToLength`/`palmThickToWidth` precisam de re-leitura
     ou o significado de largura/espessura no biomodelo difere.

3. **Espessuras de falange/polegar subestimadas (~−50%).** Todas as `Espessura *` ficam
   ~metade do scan. Como derivam de `palmThick` (que já está subestimado, ver #2), o erro
   se propaga. Calibrar `palmThick` deve corrigir boa parte em cascata.

4. **Bons encaixes (já perto):** `Comp Metacarpo Polegar` (+1.7%), `Comp Falange Dist Polegar`
   (+9%), `Comp Falange Prox Polegar` (+17%), `Comp Falange Media 1` (−4%). Os comprimentos
   do polegar e alguns segmentos médios já batem razoavelmente — bom sinal para `THUMB_RATIOS`
   e para o placeholder `THUMB_METACARPAL_TO_THUMBTOTAL=0.90`.

## Como reproduzir

```bash
python runtime/diagnose_anthropometry.py                 # masculino P50 idade 30
python runtime/diagnose_anthropometry.py feminino 75 25  # outro perfil
```

Visão [A] = divergência total (tamanho + proporção). Visão [B] = ancorada no
`Comp Metacarpo` do scan → isola divergência de **proporção** (a que importa para calibrar ratios).

## Próximo (quando entrar a calibração — pós-automações)

- Decidir a semântica da âncora (#1) — possivelmente medir a palma anatômica no `Scan_Edu_MaoEspalmada`.
- Re-derivar `palmWidthToLength` / `palmThickToWidth` a partir do scan (#2, #3).
- Tratar o biomodelo como um sexo/percentil específico e ajustar só os ratios divergentes.
