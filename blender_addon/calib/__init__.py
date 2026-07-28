"""Scan-driven calibration of the parametric GN biomodel.

This package is the new flow: a reference scan is imported, positioned over the
parametric biomodel, and the biomodel's parameters are solved so it reproduces
that specific hand. It replaces the legacy path (rigging plus sculpt-mode
post-processing) and has no relationship to the anthropometric percentile code
in ``biomodel/anthropometry.py``.

Deliberately imports nothing from the bridge side (``server``, ``tools``,
``capture``) so the whole package can be lifted into a standalone Blender 5.2
addon once it stabilises.

Modules:

* ``metrics`` -- how good is a fit, in millimetres, on the region the scan
  actually covers;
* ``align`` -- rigid placement of the scan onto the biomodel.
"""

from __future__ import annotations

from .metrics import coverage_mask, residual, scan_bvh, summarise
from .align import apply_transform, icp, kabsch

__all__ = [
    "coverage_mask",
    "residual",
    "scan_bvh",
    "summarise",
    "apply_transform",
    "icp",
    "kabsch",
]
