"""Camada antropométrica — deriva as dimensões do biomodelo de poucas entradas.

⚠️ CONTRATO DEFASADO (2026-06-16): este derivador mapeia o contrato ANTIGO de 2 cadeias
de dedos. A árvore viva `Biomodelo` foi reestruturada para **4 dedos individuais + sistema
MCP** (58 sockets). A fonte de verdade do contrato agora é `presets/biomodel_sockets_live.json`
e `source_template.py` (reconciliados). Reescrever `DERIVED_SOCKETS`/`POSE_SOCKETS` e a
derivação para os 4 dedos é trabalho da CALIBRAÇÃO (front PARADA por decisão do usuário —
"automações antes da calibração"). Não rodar `apply` desta camada na árvore atual sem essa
reconciliação (risco da mão deformada). Ver `docs/SOCKET_CONTRACT_RECONCILE_2026-06-16.md`.

Porte histórico das tabelas de proporção do simulador web original:
- `src/constants/anthropometry.js`  → PALM_DIMS, RATIOS, PHAL_RATIOS, THUMB_RATIOS,
  TIP_SOFT_MM, SEX_RATIOS, THUMB_BASE_RATIO
- `src/utils/anthropometry/profile.js` → interpPercentileScale, ageScale, buildProfile, makeDims
- `src/constants/biomechanics.js`   → RANGES (ranges clínicos), OPP_COUPLING

Cálculo PURO em milímetros e graus — este módulo **não importa bpy** e é testável
fora do Blender. A Etapa 3 (addon/UI) é que vai escrever `derive_params(...)` nos
sockets do modifier.

Mapeamento p/ as 2 cadeias do biomodelo (decisão do plano, seção 2.3.2):
- Dedo 1 (radial)  ← média de D2 (indicador) e D3 (médio)
- Dedo 2 (ulnar)   ← média de D4 (anelar)  e D5 (mínimo)

Ver `docs/PLANO_ADDON_ANTROPOMETRICO.md` (Etapa 1).
"""

from __future__ import annotations

import math
from typing import Optional

__all__ = [
    "PALM_DIMS", "THUMB_BASE_RATIO", "RATIOS", "PHAL_RATIOS", "THUMB_RATIOS",
    "TIP_SOFT_MM", "SEX_RATIOS", "RANGES", "OPP_COUPLING", "DIP_TO_PIP",
    "THUMB_METACARPAL_TO_THUMBTOTAL", "DERIVED_SOCKETS", "POSE_SOCKETS", "ANCHOR_SOCKET",
    "interp_percentile_scale", "age_scale", "build_profile", "make_dims",
    "derive_socket_values", "derive_params",
]


# ---------------------------------------------------------------------------
# Constantes — espelho de src/constants/anthropometry.js (valores idênticos)
# ---------------------------------------------------------------------------

PALM_DIMS = {"LENGTH": 70.0, "THICKNESS": 14.0, "WIDTH": 55.0}

THUMB_BASE_RATIO = {"xL": 24.0 / 70.0, "yT": -2.0 / 14.0, "zW": 0.54}

RATIOS = {
    "baseZ": [18.0 / 55.0, 6.0 / 55.0, -6.0 / 55.0, -18.0 / 55.0],
    "fingerWidths": [10.0 / 14.0, 9.0 / 14.0, 8.0 / 14.0],   # prox, média, distal
    "thumbWidths": [10.0 / 14.0, 9.0 / 14.0],                # prox, distal
}

# Comprimentos de falange: fração do dedo médio (D3) + segmentação interna.
# Ordem de inserção (D2..D5) é significativa para a agregação em cadeias.
PHAL_RATIOS = {
    "D2": {"totalVsD3": 0.882, "seg": {"pp": 0.51, "pm": 0.287, "pd": 0.203}},
    "D3": {"totalVsD3": 1.0, "seg": {"pp": 0.505, "pm": 0.298, "pd": 0.197}},
    "D4": {"totalVsD3": 0.954, "seg": {"pp": 0.491, "pm": 0.304, "pd": 0.205}},
    "D5": {"totalVsD3": 0.756, "seg": {"pp": 0.49, "pm": 0.271, "pd": 0.239}},
}

THUMB_RATIOS = {"totalVsD3": 0.66, "seg": {"pp": 0.593, "pd": 0.407}}

TIP_SOFT_MM = {"D2": 3.84, "D3": 3.95, "D4": 3.95, "D5": 3.73, "TH": 5.67}

SEX_RATIOS = {
    "masculino": {
        "palmWidthToLength": 0.8,
        "palmThickToWidth": 0.27,
        "wristRadToPalmWidth": 0.3,
        "wristLenToPalmThick": 1.1,
        "forearmLenToPalmLen": 1.75,
        "forearmProxToWrist": 1.15,
        "forearmDistToWrist": 0.9,
        "d3ToPalm": 1.03,
        "thumbBaseFromProx": 0.21,
    },
    "feminino": {
        "palmWidthToLength": 0.82,
        "palmThickToWidth": 0.25,
        "wristRadToPalmWidth": 0.29,
        "wristLenToPalmThick": 1.05,
        "forearmLenToPalmLen": 1.7,
        "forearmProxToWrist": 1.1,
        "forearmDistToWrist": 0.88,
        "d3ToPalm": 0.99,
        "thumbBaseFromProx": 0.19,
    },
}

# Ranges clínicos (graus) — src/constants/biomechanics.js. Para Etapas 2/4.
RANGES = {
    "MCP": (-45, 90), "PIP": (0, 100), "DIP": (-20, 80),
    "CMC_ABD": (-15, 70), "CMC_FLEX": (-70, 15),
    "THUMB_MCP_FLEX": (0, 60), "THUMB_IP": (-10, 80),
    "WRIST_FLEX": (-70, 80), "WRIST_DEV": (-20, 30),
}

# Acoplamento da oposição do polegar (Kapandji → 3 rotações). Para Etapa 4.
OPP_COUPLING = {"ABD_GAIN": 0.18, "FLEX_GAIN": 0.22, "PRONATION_GAIN": 0.38}

# Acoplamento DIP = 0.6 × PIP (tendão flexor compartilhado). defaults.js. Etapa 4.
DIP_TO_PIP = 0.6

# Circunferência = 2π·raio. A árvore agora recebe PERÍMETRO nos sockets de antebraço
# (medição por trena) e converte para raio com ÷(2π); a camada antropométrica
# devolve perímetro multiplicando o raio derivado por TAU.
TAU = 2.0 * math.pi

# ---------------------------------------------------------------------------
# CALIBRAR — o simulador modela o polegar em 2 segmentos (falange prox + dist),
# sem um metacarpo do polegar separado. O biomodelo tem 3 ossos no polegar
# (metacarpo + falange prox + falange dist), então o comprimento do metacarpo do
# polegar (Socket_33) não tem fonte genérica. Placeholder anatômico até a
# calibração contra os scans reais. Ver Apêndice A / decisão 2.3.3 do plano.
THUMB_METACARPAL_TO_THUMBTOTAL = 0.90  # CALIBRAR


# ---------------------------------------------------------------------------
# Classificação dos 31 sockets (identifier) — DERIVADO (tamanho) vs POSE
# ---------------------------------------------------------------------------

ANCHOR_SOCKET = "Socket_29"  # Comp Metacarpo = comprimento da palma (âncora)

# Refatoração 2026-06-13: a árvore passou a derivar TODAS as espessuras de falange/
# polegar de uma única "Espessura da Palma" (Socket_31) por ratios anatômicos, e os
# sockets de raio viraram PERÍMETRO (a árvore divide por 2π). Logo a camada
# antropométrica só escreve 15 sockets de tamanho — as espessuras saíram da interface.
DERIVED_SOCKETS = (
    # Antebraço
    "Socket_21",  # Comp Antebraço
    "Socket_22",  # Perímetro Cotovelo  (= raio × 2π)
    "Socket_23",  # Perímetro Punho     (= raio × 2π)
    # Palma
    "Socket_29",  # Comp Metacarpo (âncora)
    "Socket_30",  # Largura Metacarpo (largura total da palma; ×2 vive na árvore)
    "Socket_31",  # Espessura da Palma (master; deriva todas as espessuras na árvore)
    # Polegar
    "Socket_33",  # Comp Metacarpo Polegar (CALIBRAR)
    "Socket_40",  # Comp Falange Prox Polegar
    "Socket_43",  # Comp Falange Dist Polegar
    # Dedo 1 (radial ← D2/D3)
    "Socket_50",  # Comp Falange Prox 1
    "Socket_53",  # Comp Falange Media 1
    "Socket_56",  # Comp Falange Dist 1
    # Dedo 2 (ulnar ← D4/D5)
    "Socket_63",  # Comp Falange Prox 2
    "Socket_66",  # Comp Falange Media 2
    "Socket_69",  # Comp Falange Dist 2
)

# 16 sockets de POSE/forma — não derivados (vêm do preset ou da entrada do clínico).
POSE_SOCKETS = (
    "Socket_24",  # Desvio Rad/Ulnar Punho
    "Socket_25",  # Flex/Ext Punho
    "Socket_27",  # Curva Palma Metacarpo 1
    "Socket_28",  # Curva Palma Metacarpo 2
    "Socket_36",  # Flex/Ext Polegar (CMC flex)
    "Socket_37",  # Abdução Polegar (CMC abd)
    "Socket_38",  # Flex/Ext Falange Prox Polegar (MCP)
    "Socket_39",  # Flex/Ext Falange Dist Polegar (IP)
    "Socket_76",  # Abdução Dedo 1
    "Socket_47",  # Flex/Ext Falange Prox 1 (MCP global)
    "Socket_48",  # Flex/Ext Falange Media 1 (PIP global)
    "Socket_49",  # Flex/Ext Falange Dist 1 (DIP = 0.6×PIP)
    "Socket_77",  # Abdução Dedo 2
    "Socket_60",  # Flex/Ext Falange Prox 2
    "Socket_61",  # Flex/Ext Falange Media 2
    "Socket_62",  # Flex/Ext Falange Dist 2
)


# ---------------------------------------------------------------------------
# Perfil + dimensões — porte fiel de profile.js
# ---------------------------------------------------------------------------

def interp_percentile_scale(p0: float) -> float:
    """interpPercentileScale: P5→0.92, P50→1.00, P95→1.08 (linear por trecho)."""
    p = min(max(p0, 5.0), 95.0)
    if p <= 50.0:
        return 0.92 + ((p - 5.0) / 45.0) * 0.08
    return 1.0 + ((p - 50.0) / 45.0) * 0.08


def age_scale(age0: float) -> float:
    """ageScale: interpolação linear por pontos etários (clamp 5–90)."""
    a = min(max(age0, 5.0), 90.0)
    pts = [(5, 0.6), (10, 0.78), (14, 0.9), (18, 1.0), (65, 1.0), (80, 0.98), (90, 0.96)]
    for i in range(len(pts) - 1):
        a0, s0 = pts[i]
        a1, s1 = pts[i + 1]
        if a0 <= a <= a1:
            return s0 + ((a - a0) / (a1 - a0)) * (s1 - s0)
    return 1.0


def build_profile(sex: str, percentile: float, age: float) -> dict:
    """buildProfile: escalas globais (palm/finger/thumb) a partir de sexo/percentil/idade."""
    male = str(sex).lower().startswith("m")
    if male:
        base = {"palmScale": 1.05, "fingerScale": 1.03, "thumbScale": 1.03, "zW_mult": 1.02}
    else:
        base = {"palmScale": 0.97, "fingerScale": 0.98, "thumbScale": 0.98, "zW_mult": 0.98}
    sc = interp_percentile_scale(percentile) * age_scale(age)
    return {
        "sex": "masculino" if male else "feminino",
        "palmScale": base["palmScale"] * sc,
        "fingerScale": base["fingerScale"] * sc,
        "thumbScale": base["thumbScale"] * sc,
        "thumbBase": {**THUMB_BASE_RATIO, "zW": THUMB_BASE_RATIO["zW"] * base["zW_mult"]},
    }


def make_dims(profile: dict) -> dict:
    """makeDims: todas as dimensões (mm) a partir do perfil. Espelha profile.js."""
    ratios = SEX_RATIOS[profile["sex"]]
    palm_len = PALM_DIMS["LENGTH"] * profile["palmScale"]
    palm_width = palm_len * ratios["palmWidthToLength"]
    palm_thick = palm_width * ratios["palmThickToWidth"]

    d3_total = ratios["d3ToPalm"] * palm_len * profile["fingerScale"]
    # ordem D2,D3,D4,D5 (insertion order de PHAL_RATIOS)
    fingers = []
    for r in PHAL_RATIOS.values():
        t = d3_total * r["totalVsD3"]
        fingers.append([t * r["seg"]["pp"], t * r["seg"]["pm"], t * r["seg"]["pd"]])

    finger_wid = [r * palm_thick for r in RATIOS["fingerWidths"]]

    thumb_total = d3_total * THUMB_RATIOS["totalVsD3"] * (profile["thumbScale"] / profile["fingerScale"])
    thumb_len = [thumb_total * THUMB_RATIOS["seg"]["pp"], thumb_total * THUMB_RATIOS["seg"]["pd"]]
    thumb_metacarpal = thumb_total * THUMB_METACARPAL_TO_THUMBTOTAL  # CALIBRAR
    thumb_wid = [r * palm_thick for r in RATIOS["thumbWidths"]]

    base_x = palm_len / 2.0 + min(max(0.3 * palm_thick, 1.5), 6.0)
    base_z = [r * palm_width for r in RATIOS["baseZ"]]
    thumb_base = {
        "x": -palm_len / 2.0 + ratios["thumbBaseFromProx"] * palm_len,
        "y": palm_thick * profile["thumbBase"].get("yT", THUMB_BASE_RATIO["yT"]),
        "z": palm_width * profile["thumbBase"].get("zW", THUMB_BASE_RATIO["zW"]),
    }

    wrist = {"radius": palm_width * ratios["wristRadToPalmWidth"],
             "length": palm_thick * ratios["wristLenToPalmThick"]}
    forearm = {
        "len": palm_len * ratios["forearmLenToPalmLen"],
        "radProx": palm_width * ratios["wristRadToPalmWidth"] * ratios["forearmProxToWrist"],
        "radDist": palm_width * ratios["wristRadToPalmWidth"] * ratios["forearmDistToWrist"],
    }

    ss = palm_len / PALM_DIMS["LENGTH"]
    tip_pads = {k.lower(): v * ss for k, v in
                {"index": TIP_SOFT_MM["D2"], "middle": TIP_SOFT_MM["D3"],
                 "ring": TIP_SOFT_MM["D4"], "little": TIP_SOFT_MM["D5"],
                 "thumb": TIP_SOFT_MM["TH"]}.items()}

    return {
        "palm": {"LENGTH": palm_len, "WIDTH": palm_width, "THICKNESS": palm_thick},
        "fingers": fingers,            # [D2, D3, D4, D5] cada [pp, pm, pd] (mm)
        "fingerWid": finger_wid,       # [prox, média, distal] (mm)
        "thumbTotal": thumb_total,
        "thumbLen": thumb_len,         # [prox, dist] (mm)
        "thumbMetacarpal": thumb_metacarpal,
        "thumbWid": thumb_wid,         # [prox, dist] (mm)
        "baseX": base_x,
        "baseZ": base_z,
        "thumbBase": thumb_base,
        "forearm": forearm,
        "wrist": wrist,
        "tipPads": tip_pads,
    }


# ---------------------------------------------------------------------------
# Mapeamento dimensões → sockets do biomodelo (2 cadeias)
# ---------------------------------------------------------------------------

def _chain(fingers: list, idx_a: int, idx_b: int) -> list:
    """Média por segmento de dois dedos (ex.: cadeia 1 = média D2/D3)."""
    a, b = fingers[idx_a], fingers[idx_b]
    return [(a[i] + b[i]) / 2.0 for i in range(3)]


def derive_socket_values(dims: dict) -> dict:
    """Converte as dimensões em {identifier: valor} para os 15 sockets DERIVADOS.

    Pós-refatoração 2026-06-13: as espessuras (falange/polegar) saíram da interface —
    a árvore as deriva da "Espessura da Palma" (Socket_31). Os sockets de antebraço
    22/23 são PERÍMETRO (= raio × 2π), pois a árvore converte de volta com ÷(2π).
    """
    palm = dims["palm"]
    c1 = _chain(dims["fingers"], 0, 1)  # D2/D3 → Dedo 1 (radial)
    c2 = _chain(dims["fingers"], 2, 3)  # D4/D5 → Dedo 2 (ulnar)

    values = {
        # Antebraço (perímetro = raio × 2π)
        "Socket_21": dims["forearm"]["len"],
        "Socket_22": dims["forearm"]["radProx"] * TAU,
        "Socket_23": dims["wrist"]["radius"] * TAU,
        # Palma
        "Socket_29": palm["LENGTH"],            # âncora
        "Socket_30": palm["WIDTH"],             # largura total da palma
        "Socket_31": palm["THICKNESS"],         # master das espessuras
        # Polegar
        "Socket_33": dims["thumbMetacarpal"],   # CALIBRAR
        "Socket_40": dims["thumbLen"][0],
        "Socket_43": dims["thumbLen"][1],
        # Dedo 1
        "Socket_50": c1[0], "Socket_53": c1[1], "Socket_56": c1[2],
        # Dedo 2
        "Socket_63": c2[0], "Socket_66": c2[1], "Socket_69": c2[2],
    }
    assert set(values) == set(DERIVED_SOCKETS), "cobertura de sockets derivados divergente"
    return values


def derive_params(sex: str, percentile: float, age: float,
                  comp_palma: Optional[float] = None) -> dict:
    """Deriva os valores de TAMANHO dos 25 sockets a partir de (sexo, percentil, idade).

    Se ``comp_palma`` for dado, escala a mão inteira UNIFORMEMENTE para que o
    comprimento da palma (âncora, Socket_29) bata exatamente nesse valor,
    preservando todas as proporções derivadas do percentil/sexo. Os sockets de
    POSE não são tocados (ficam por conta do preset / clínico).
    """
    profile = build_profile(sex, percentile, age)
    dims = make_dims(profile)
    values = derive_socket_values(dims)
    if comp_palma is not None and comp_palma > 0:
        s = float(comp_palma) / values[ANCHOR_SOCKET]
        values = {k: v * s for k, v in values.items()}
    return values
