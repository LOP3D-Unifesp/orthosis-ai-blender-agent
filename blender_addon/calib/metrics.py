"""Fit quality between the biomodel and a reference scan, in millimetres.

The one thing this module exists to get right: **a residual computed over the
whole biomodel is not a fit error.** The biomodel carries a forearm the scan
does not reach, so its far vertices sit ~100 mm from anything and drag every
aggregate with them. Measured on P01 (2026-07-26):

    all 1762 verts          median 3.60   p90 11.26   max 123.13
    1720 inside envelope    median 3.52   p90 10.46   max  20.88
    42 outside envelope     median 106.65 p90 122.54  max 123.13

The two populations do not overlap -- inside never exceeds 21 mm, outside never
drops below ~100 -- so an axis-aligned envelope test separates them cleanly and
nothing subtler is warranted yet. Every number reported for publication must be
the regionalised one, with coverage stated alongside it.

Same discipline as the rest of the project: prove geometry by measurement, not
by looking at a render.
"""

from __future__ import annotations

from typing import Any

import bpy


# ---------------------------------------------------------------------------
# Geometry access
# ---------------------------------------------------------------------------


def _require(name: str):
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"object not found: {name!r}")
    if obj.type != "MESH":
        raise ValueError(f"object {name!r} is a {obj.type}, expected MESH")
    return obj


def evaluated_world_geometry(name: str):
    """Return ``(obj, points, triangles)`` for the evaluated mesh, in world space.

    Evaluated, not raw: the biomodel is Geometry Nodes output, so ``obj.data``
    holds an 8-vertex base cube and tells us nothing.
    """
    from mathutils import Vector  # noqa: F401  (imported for callers' typing)

    obj = _require(name)
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    mesh = ev.to_mesh()
    try:
        mw = obj.matrix_world
        points = [tuple(mw @ v.co) for v in mesh.vertices]
        tris = [tuple(p.vertices) for p in mesh.polygons]
    finally:
        # to_mesh_clear is mandatory; skipping it leaks the temporary mesh.
        ev.to_mesh_clear()
    return obj, points, tris


def scan_bvh(scan: str):
    """Build a BVH over the scan's evaluated surface in world space.

    Returned alongside the scan's world-space bounding box, which is what the
    coverage test needs. Build once and reuse -- on a 950k-triangle scan this is
    the expensive step, and callers that iterate (ICP) must not rebuild it.
    """
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree

    _obj, points, tris = evaluated_world_geometry(scan)
    if not tris:
        raise ValueError(f"scan {scan!r} has no faces to build a BVH from")
    bvh = BVHTree.FromPolygons([Vector(p) for p in points], tris)

    lo = [min(p[i] for p in points) for i in range(3)]
    hi = [max(p[i] for p in points) for i in range(3)]
    return bvh, (lo, hi)


# ---------------------------------------------------------------------------
# Coverage and residual
# ---------------------------------------------------------------------------


def coverage_mask(points, bbox, margin: float = 0.0) -> list[bool]:
    """Which biomodel points fall inside the scan's world-space envelope.

    ``margin`` in millimetres grows the envelope; a small positive value keeps
    vertices that sit just outside a slightly-clipped scan boundary. Axis-aligned
    by design -- see the module docstring for why that suffices here.
    """
    lo, hi = bbox
    return [
        all(lo[i] - margin <= p[i] <= hi[i] + margin for i in range(3))
        for p in points
    ]


def summarise(values) -> dict[str, Any] | None:
    """Distribution summary in millimetres. ``None`` for an empty input."""
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    n = len(v)

    def q(f: float) -> float:
        return round(v[min(n - 1, int(f * n))], 4)

    return {
        "n": n,
        "media": round(sum(v) / n, 4),
        "mediana": q(0.5),
        "p90": q(0.9),
        "p95": q(0.95),
        "max": round(v[-1], 4),
    }


def residual(
    biomodel: str,
    scan: str,
    *,
    margin: float = 0.0,
    bvh=None,
    bbox=None,
    histogram_edges=(1.0, 2.0, 4.0, 8.0, 16.0, 32.0),
) -> dict[str, Any]:
    """Distance from each biomodel vertex to the nearest point on the scan.

    Reports the regionalised figure (``dentro``) as the headline, the raw
    whole-mesh figure (``todos``) for comparison, and ``cobertura_pct`` so a
    reader can tell how much of the biomodel the scan actually constrains.

    Pass ``bvh``/``bbox`` from :func:`scan_bvh` to reuse a build across calls.
    """
    from mathutils import Vector

    if bvh is None or bbox is None:
        bvh, bbox = scan_bvh(scan)

    _obj, points, _tris = evaluated_world_geometry(biomodel)
    if not points:
        raise ValueError(f"biomodel {biomodel!r} evaluated to zero vertices")

    distances = [bvh.find_nearest(Vector(p))[3] for p in points]
    inside = coverage_mask(points, bbox, margin=margin)

    d_in = [d for d, ok in zip(distances, inside) if ok]
    d_out = [d for d, ok in zip(distances, inside) if not ok]

    edges = list(histogram_edges)
    hist: dict[str, int] = {}
    prev = 0.0
    for e in edges:
        hist[f"{prev:g}-{e:g}mm"] = sum(1 for d in d_in if d is not None and prev <= d < e)
        prev = e
    hist[f"{prev:g}+mm"] = sum(1 for d in d_in if d is not None and d >= prev)

    return {
        "biomodelo": biomodel,
        "scan": scan,
        "margem_mm": margin,
        "cobertura_pct": round(100.0 * len(d_in) / len(distances), 2),
        "dentro": summarise(d_in),
        "fora": summarise(d_out),
        "todos": summarise(distances),
        "histograma_dentro": hist,
        "distancias": distances,
        "dentro_mask": inside,
    }
