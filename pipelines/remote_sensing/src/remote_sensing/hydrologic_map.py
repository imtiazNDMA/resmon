"""Pure preparation helpers for HydroSHEDS-style hydrologic map layers.

This module is the testable spine for Phase 8A.3. It deliberately avoids a heavy GIS
dependency: geometry clipping/DEM work happens in GEE/PostGIS later, while topology,
resolution policy, and QA flags stay pure Python and unit-testable.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Literal

GeometryResolution = Literal["raw", "web", "export"]
QualityFlag = Literal[
    "duplicate_hybas_id",
    "missing_downstream",
    "cycle_detected",
    "outlet_basin",
]


@dataclass(frozen=True)
class GeometryResolutionSpec:
    name: GeometryResolution
    simplify_tolerance_deg: float
    intended_use: str


GEOMETRY_RESOLUTIONS: tuple[GeometryResolutionSpec, ...] = (
    GeometryResolutionSpec("raw", 0.0, "internal processing and QA"),
    GeometryResolutionSpec("web", 0.0001, "interactive Leaflet overlays"),
    GeometryResolutionSpec("export", 0.00005, "static map exports and reports"),
)


@dataclass(frozen=True)
class PreparedSubbasin:
    hybas_id: int
    next_down: int
    is_headwater: bool
    downstream_path_length: int | None
    quality_flags: tuple[QualityFlag, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PreparedSubbasinTopology:
    subbasins: tuple[PreparedSubbasin, ...]
    headwater_ids: frozenset[int]
    outlet_ids: frozenset[int]
    quality_flags: tuple[QualityFlag, ...]


def resolution_spec(name: GeometryResolution) -> GeometryResolutionSpec:
    for spec in GEOMETRY_RESOLUTIONS:
        if spec.name == name:
            return spec
    raise ValueError(f"unknown geometry resolution: {name}")


def _int_value(row: Mapping, key: str) -> int:
    value = row.get(key)
    if value is None:
        raise ValueError(f"missing required HydroBASINS field {key!r}")
    return int(value)


def _path_length_to_outlet(hybas_id: int, next_by_id: Mapping[int, int]) -> tuple[int | None, bool]:
    seen: set[int] = set()
    current = hybas_id
    length = 0
    while True:
        if current in seen:
            return None, True
        seen.add(current)
        next_down = next_by_id.get(current, 0)
        if next_down == 0 or next_down not in next_by_id:
            return length, False
        current = next_down
        length += 1


def prepare_subbasin_topology(rows: Iterable[Mapping]) -> PreparedSubbasinTopology:
    """Derive topology attributes and QA flags from HydroBASINS rows.

    Input rows must include ``hybas_id``/``HYBAS_ID`` and ``next_down``/``NEXT_DOWN``.
    ``next_down = 0`` is treated as the outlet. A downstream id outside the selected
    catchment is flagged as missing downstream; this is expected at the outlet only.
    """
    normalized = []
    for row in rows:
        hybas_id = _int_value(row, "hybas_id") if "hybas_id" in row else _int_value(row, "HYBAS_ID")
        next_down = (
            _int_value(row, "next_down") if "next_down" in row else _int_value(row, "NEXT_DOWN")
        )
        normalized.append((hybas_id, next_down))

    counts = Counter(hybas_id for hybas_id, _ in normalized)
    duplicate_ids = {hybas_id for hybas_id, count in counts.items() if count > 1}
    next_by_id = {hybas_id: next_down for hybas_id, next_down in normalized}
    fed_ids = {next_down for _, next_down in normalized if next_down in next_by_id}
    headwater_ids = frozenset(hybas_id for hybas_id, _ in normalized if hybas_id not in fed_ids)
    outlet_ids = frozenset(hybas_id for hybas_id, next_down in normalized if next_down == 0)

    prepared = []
    global_flags: set[QualityFlag] = set()
    for hybas_id, next_down in normalized:
        flags: list[QualityFlag] = []
        if hybas_id in duplicate_ids:
            flags.append("duplicate_hybas_id")
        if next_down == 0:
            flags.append("outlet_basin")
        elif next_down not in next_by_id:
            flags.append("missing_downstream")
        path_length, has_cycle = _path_length_to_outlet(hybas_id, next_by_id)
        if has_cycle:
            flags.append("cycle_detected")
        global_flags.update(flags)
        prepared.append(
            PreparedSubbasin(
                hybas_id=hybas_id,
                next_down=next_down,
                is_headwater=hybas_id in headwater_ids,
                downstream_path_length=path_length,
                quality_flags=tuple(flags),
            )
        )

    return PreparedSubbasinTopology(
        subbasins=tuple(prepared),
        headwater_ids=headwater_ids,
        outlet_ids=outlet_ids,
        quality_flags=tuple(sorted(global_flags)),
    )
