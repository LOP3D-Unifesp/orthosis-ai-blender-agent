"""Rigid placement of a reference scan onto the parametric biomodel.

Faithful to how the operator does it by hand: a coarse pose judged across the
orthogonal views, then iterative refinement until it stops improving. Measured
on P01 (2026-07-26), starting from a manual pose and refining:

    manual      median 9.34 mm
    refined     median 3.59 mm      (51 iterations, stopped on patience)

    axis    manual     refined    delta
    X      -27.73     -42.44     -14.7   <- front view, judged worst
    Y       -0.99       +7.01      +8.0
    Z      +70.62     +68.36       -2.3   <- top view, judged well

Two deliberate choices:

* **Nothing is applied.** :func:`icp` computes and returns; only an explicit
  :func:`apply_transform` touches the scene. A calibration routine that silently
  moves the operator's scan is not trustworthy.
* **Trimmed correspondences.** The worst fraction of pairs is dropped each
  iteration, because the biomodel's forearm has no scan under it and those pairs
  would otherwise steer the whole fit. See ``metrics`` for the measurement.

Scale is never solved for: the scanner already delivers millimetres, confirmed
by the manual pose sitting at scale exactly 1.0. Size differences belong in the
biomodel's length parameters, not in a scan transform.
"""

from __future__ import annotations

from typing import Any

from .metrics import evaluated_world_geometry, scan_bvh, summarise


# ---------------------------------------------------------------------------
# Closed-form rigid fit
# ---------------------------------------------------------------------------


def kabsch(Q, P):
    """Rigid transform taking point set ``Q`` onto ``P``. Returns a 4x4 list.

    Rotation plus translation only. The determinant correction is what keeps a
    degenerate correspondence from producing a mirrored solution, which would
    read as a plausible-looking fit of the wrong hand.
    """
    import numpy as np

    Q = np.asarray(Q, dtype=np.float64)
    P = np.asarray(P, dtype=np.float64)
    if Q.shape != P.shape or Q.shape[0] < 3:
        raise ValueError(f"need matching point sets of length >= 3, got {Q.shape} and {P.shape}")

    cq, cp = Q.mean(axis=0), P.mean(axis=0)
    H = (Q - cq).T @ (P - cp)
    U, _S, Vt = np.linalg.svd(H)
    D = np.diag([1.0, 1.0, float(np.sign(np.linalg.det(Vt.T @ U.T)))])
    R = Vt.T @ D @ U.T

    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = cp - R @ cq
    return [list(row) for row in M]


# ---------------------------------------------------------------------------
# Iterative refinement
# ---------------------------------------------------------------------------


def icp(
    biomodel: str,
    scan: str,
    *,
    max_iter: int = 150,
    trim: float = 0.8,
    patience: int = 12,
    tol: float = 1e-5,
) -> dict[str, Any]:
    """Refine the scan's placement. Computes only -- does not modify the scene.

    Starts from wherever the scan currently sits, so a manual coarse pose is
    honoured as the initial guess rather than discarded.

    The BVH is built once in the scan's *current* world space and never rebuilt;
    each iteration maps biomodel points back through the accumulated transform
    to query it. Returns the best iteration seen, not the last one -- the
    residual is not monotonic and the final step is often slightly worse.

    Result carries ``matriz`` (4x4, apply on top of the scan's current
    ``matrix_world``), ``antes``/``depois`` summaries, and the convergence curve.
    """
    from mathutils import Matrix, Vector

    bvh, _bbox = scan_bvh(scan)
    scan_obj = _obj_of(scan)
    bio_obj, bio_points, _tris = evaluated_world_geometry(biomodel)
    if not bio_points:
        raise ValueError(f"biomodel {biomodel!r} evaluated to zero vertices")

    original = Matrix(scan_obj.matrix_world)

    def probe(A_inv):
        ds, qs = [], []
        for p in bio_points:
            loc, _nor, _idx, dist = bvh.find_nearest(A_inv @ Vector(p))
            ds.append(dist)
            qs.append(loc)
        return ds, qs

    A = Matrix.Identity(4)
    ds, qs = probe(A.inverted())
    before = summarise(ds)

    best_median = before["mediana"]
    best_A = Matrix(A)
    stalled = 0
    curve = [best_median]

    keep_min = 12
    for _ in range(max_iter):
        pairs = [
            (tuple(q), p, d)
            for q, p, d in zip(qs, bio_points, ds)
            if q is not None and d is not None
        ]
        if len(pairs) < keep_min:
            break
        pairs.sort(key=lambda x: x[2])
        pairs = pairs[: max(keep_min, int(trim * len(pairs)))]

        Q = [tuple(A @ Vector(pr[0])) for pr in pairs]
        P = [pr[1] for pr in pairs]
        A = Matrix(kabsch(Q, P)) @ A

        ds, qs = probe(A.inverted())
        median = summarise(ds)["mediana"]
        curve.append(median)

        if median < best_median - tol:
            best_median, best_A, stalled = median, Matrix(A), 0
        else:
            stalled += 1
            if stalled >= patience:
                break

    ds, _qs = probe(best_A.inverted())
    proposed = best_A @ original
    loc, rot, scale = proposed.decompose()

    return {
        "aplicado": False,
        "biomodelo": biomodel,
        "scan": scan,
        "iteracoes": len(curve) - 1,
        "parou_por": "paciencia" if stalled >= patience else "max_iter",
        "trim": trim,
        "antes": before,
        "depois": summarise(ds),
        "curva_mediana": [round(c, 4) for c in curve],
        "matriz": [[float(v) for v in row] for row in best_A],
        "scan_matrix_world_original": [[float(v) for v in row] for row in original],
        "proposta": {
            "loc": [round(v, 5) for v in loc],
            "rot_graus": _degrees(rot.to_euler()),
            "escala": [round(v, 5) for v in scale],
        },
    }


def apply_transform(scan: str, matriz) -> dict[str, Any]:
    """Apply a 4x4 on top of the scan's current ``matrix_world``.

    The only function here that mutates the scene. Returns the previous matrix so
    the caller can record it -- the manual pose is the baseline the automatic
    routine is measured against, and losing it costs a session.
    """
    from mathutils import Matrix

    obj = _obj_of(scan)
    previous = Matrix(obj.matrix_world)
    obj.matrix_world = Matrix(matriz) @ previous
    return {
        "aplicado": True,
        "scan": scan,
        "anterior": [[float(v) for v in row] for row in previous],
        "atual": [[float(v) for v in row] for row in obj.matrix_world],
        "rot_anterior_graus": _degrees(previous.to_euler()),
        "rot_atual_graus": _degrees(obj.rotation_euler),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _obj_of(name: str):
    import bpy

    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"object not found: {name!r}")
    return obj


def _degrees(euler) -> list[float]:
    import math

    return [round(math.degrees(a), 3) for a in euler]
