"""Map simulator JSON payloads into atomic GN set_node_value operations."""

from __future__ import annotations

from typing import Any


DEFAULT_MAPPING = {
    "wrist_circumference_mm": ("VM_Measures", "wrist_mm"),
    "forearm_circumference_mm": ("VM_Measures", "forearm_mm"),
    "orthosis_length_mm": ("VM_Measures", "length_mm"),
    "wall_thickness_mm": ("VM_Measures", "thickness_mm"),
    "clearance_mm": ("VM_Measures", "clearance_mm"),
}


def _to_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip().replace(",", ".")
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def build_gn_ops_from_simulator_payload(
    *,
    tree_name: str,
    payload: dict[str, Any],
    mapping: dict[str, Any] | None = None,
    strict: bool = False,
) -> list[dict[str, Any]]:
    """Return a list of ``set_node_value`` operations.

    Mapping format:
      {
        "payload_key": ["NodeName", "Socket Name"]
      }
    """
    _ = tree_name  # reserved for future per-tree validation
    effective_mapping = mapping or DEFAULT_MAPPING
    ops: list[dict[str, Any]] = []
    missing_keys: list[str] = []
    invalid_values: list[str] = []

    for payload_key, target in effective_mapping.items():
        if payload_key not in payload:
            missing_keys.append(payload_key)
            continue
        if not isinstance(target, (list, tuple)) or len(target) != 2:
            if strict:
                raise ValueError(f"Invalid mapping for '{payload_key}': expected [node_name, socket_name].")
            continue
        node_name = str(target[0]).strip()
        socket_name = str(target[1]).strip()
        if not node_name or not socket_name:
            if strict:
                raise ValueError(f"Invalid mapping for '{payload_key}': empty node/socket.")
            continue

        numeric_value = _to_float(payload[payload_key])
        if numeric_value is None:
            invalid_values.append(payload_key)
            continue

        ops.append(
            {
                "op": "set_node_value",
                "params": {
                    "node": node_name,
                    "socket": socket_name,
                    "value": numeric_value,
                },
            }
        )

    if strict:
        problems = []
        if missing_keys:
            problems.append(f"missing keys: {missing_keys}")
        if invalid_values:
            problems.append(f"invalid numeric values: {invalid_values}")
        if problems:
            raise ValueError("Simulator payload mapping failed (" + "; ".join(problems) + ")")

    return ops

