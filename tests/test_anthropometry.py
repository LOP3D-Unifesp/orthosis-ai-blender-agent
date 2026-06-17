"""Testes da camada antropométrica (Etapa 1). Cálculo puro, sem Blender.

Carrega `anthropometry.py` por caminho para evitar `blender_addon/__init__.py`
(que importa bpy). Valores de referência conferidos à mão a partir das fórmulas
de `profile.js` para garantir fidelidade ao simulador.
"""

import importlib.util
import math
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "anthropometry", ROOT / "blender_addon" / "biomodel" / "anthropometry.py"
)
anthro = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(anthro)


def approx(x):
    return pytest.approx(x, rel=1e-9, abs=1e-9)


# --- escalas de percentil / idade -----------------------------------------

def test_percentile_scale_anchors():
    assert anthro.interp_percentile_scale(5) == approx(0.92)
    assert anthro.interp_percentile_scale(50) == approx(1.0)
    assert anthro.interp_percentile_scale(95) == approx(1.08)


def test_percentile_scale_clamps():
    assert anthro.interp_percentile_scale(-10) == anthro.interp_percentile_scale(5)
    assert anthro.interp_percentile_scale(200) == anthro.interp_percentile_scale(95)


def test_age_scale_anchors_and_plateau():
    assert anthro.age_scale(5) == approx(0.6)
    assert anthro.age_scale(18) == approx(1.0)
    assert anthro.age_scale(40) == approx(1.0)   # platô 18–65
    assert anthro.age_scale(90) == approx(0.96)
    # ponto interpolado: idade 10 → 0.78
    assert anthro.age_scale(10) == approx(0.78)


# --- perfil ----------------------------------------------------------------

def test_build_profile_male_p50_age30():
    p = anthro.build_profile("masculino", 50, 30)
    assert p["sex"] == "masculino"
    assert p["palmScale"] == approx(1.05)
    assert p["fingerScale"] == approx(1.03)
    assert p["thumbScale"] == approx(1.03)


def test_build_profile_female_scales_down():
    p = anthro.build_profile("feminino", 50, 30)
    assert p["palmScale"] == approx(0.97)
    assert p["sex"] == "feminino"


# --- dimensões (valores conferidos à mão) ----------------------------------

@pytest.fixture
def dims_male():
    return anthro.make_dims(anthro.build_profile("masculino", 50, 30))


def test_palm_dims_male(dims_male):
    palm = dims_male["palm"]
    assert palm["LENGTH"] == approx(73.5)              # 70 * 1.05
    assert palm["WIDTH"] == approx(58.8)               # 73.5 * 0.80
    assert palm["THICKNESS"] == approx(15.876)         # 58.8 * 0.27


def test_d3_total_and_chain_aggregation(dims_male):
    d3_total = 1.03 * 73.5 * 1.03                      # 77.97615
    fingers = dims_male["fingers"]
    # D3 proximal = d3_total * 1.0 * 0.505
    assert fingers[1][0] == approx(d3_total * 0.505)
    # cadeia 1 proximal = média(D2 pp, D3 pp)
    d2_pp = d3_total * 0.882 * 0.51
    d3_pp = d3_total * 1.0 * 0.505
    vals = anthro.derive_socket_values(dims_male)
    assert vals["Socket_50"] == approx((d2_pp + d3_pp) / 2.0)


def test_forearm_and_wrist(dims_male):
    assert dims_male["wrist"]["radius"] == approx(58.8 * 0.3)        # 17.64
    assert dims_male["forearm"]["len"] == approx(73.5 * 1.75)        # 128.625
    assert dims_male["forearm"]["radProx"] == approx(58.8 * 0.3 * 1.15)
    assert dims_male["forearm"]["radDist"] == approx(58.8 * 0.3 * 0.9)


def test_finger_and_thumb_widths(dims_male):
    pt = 15.876
    fw = dims_male["fingerWid"]
    assert fw[0] == approx((10 / 14) * pt)
    assert fw[1] == approx((9 / 14) * pt)
    assert fw[2] == approx((8 / 14) * pt)
    tw = dims_male["thumbWid"]
    assert tw[0] == approx((10 / 14) * pt)
    assert tw[1] == approx((9 / 14) * pt)


# --- derive_params / sockets -----------------------------------------------

def test_derive_params_covers_all_derived_sockets():
    vals = anthro.derive_params("masculino", 50, 30)
    assert set(vals) == set(anthro.DERIVED_SOCKETS)
    assert len(vals) == 15
    # nenhum socket de pose vaza para o resultado
    assert not (set(vals) & set(anthro.POSE_SOCKETS))


def test_derived_and_pose_partition_is_clean():
    d = set(anthro.DERIVED_SOCKETS)
    p = set(anthro.POSE_SOCKETS)
    assert len(d) == 15 and len(p) == 16
    assert d.isdisjoint(p)
    assert len(d | p) == 31               # contrato pós-refatoração (41 → 31 sockets)
    assert anthro.ANCHOR_SOCKET in d


def test_perimeter_sockets_are_radius_times_tau(dims_male):
    """Sockets 22/23 (antebraço) devem sair em PERÍMETRO = raio × 2π."""
    vals = anthro.derive_socket_values(dims_male)
    assert vals["Socket_22"] == approx(dims_male["forearm"]["radProx"] * anthro.TAU)
    assert vals["Socket_23"] == approx(dims_male["wrist"]["radius"] * anthro.TAU)


def test_comp_palma_override_uniform_scale():
    base = anthro.derive_params("masculino", 50, 30)
    target = 100.0
    scaled = anthro.derive_params("masculino", 50, 30, comp_palma=target)
    # âncora bate exatamente
    assert scaled[anthro.ANCHOR_SOCKET] == approx(target)
    # escala uniforme: razões preservadas
    s = target / base[anthro.ANCHOR_SOCKET]
    for k in base:
        assert scaled[k] == approx(base[k] * s)


def test_all_derived_values_positive():
    vals = anthro.derive_params("feminino", 25, 12)
    for k, v in vals.items():
        assert v > 0, f"{k} não-positivo: {v}"


def test_bigger_percentile_means_bigger_hand():
    p5 = anthro.derive_params("masculino", 5, 30)
    p95 = anthro.derive_params("masculino", 95, 30)
    for k in p5:
        assert p95[k] > p5[k]


def test_thumb_metacarpal_flagged_constant_used():
    dims = anthro.make_dims(anthro.build_profile("masculino", 50, 30))
    assert dims["thumbMetacarpal"] == approx(
        dims["thumbTotal"] * anthro.THUMB_METACARPAL_TO_THUMBTOTAL
    )


def test_ranges_present_for_pose():
    for key in ("MCP", "PIP", "DIP", "CMC_ABD", "CMC_FLEX",
                "THUMB_MCP_FLEX", "THUMB_IP", "WRIST_FLEX", "WRIST_DEV"):
        assert key in anthro.RANGES
        lo, hi = anthro.RANGES[key]
        assert lo < hi
