"""Canonical reservoir registry: bulletin name → slug + static metadata + dam point.

The slug is the ``reservoir_id`` everywhere (plan 02 §4.2). Dam coordinates seed
catchment delineation (FR-DE-7) and a placeholder AOI until RS derives the real one
from JRC GSW (Phase 3). FRL/capacity mirror ``build_unified_dataset.py`` REGISTRY.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReservoirMeta:
    slug: str
    name: str
    basin: str
    frl_m: float
    live_capacity_bcm: float
    dam_lon: float
    dam_lat: float
    orbit_relative: int  # frozen by the 2026-07-03 scene-inventory recon (D1)
    pass_direction: str


# Bulletin canonical name (from build_unified_dataset.canonical_name) → metadata.
REGISTRY: dict[str, ReservoirMeta] = {
    "GOBIND SAGAR": ReservoirMeta(
        "gobind_sagar", "Gobind Sagar", "Sutlej", 512.00, 6.229, 76.4604, 31.4112, 27, "ASC"
    ),
    "PONG DAM": ReservoirMeta(
        "pong", "Pong Dam", "Beas", 423.67, 6.157, 76.0913, 31.9669, 27, "ASC"
    ),
    # Dam-wall coordinates verified against JRC GSW max-extent (2026-07-03 recon):
    # the previous placeholder (75.65, 32.42) sat ~8 km SW of the dam with no water
    # within 1 km, so AOI derivation (dam-connected component) correctly failed.
    "THEIN DAM": ReservoirMeta(
        "thein", "Thein Dam", "Ravi", 527.91, 2.344, 75.7303, 32.4431, 27, "ASC"
    ),
}

SLUGS = {m.slug for m in REGISTRY.values()}


def meta_for_name(bulletin_name: object) -> ReservoirMeta | None:
    if not isinstance(bulletin_name, str):
        return None
    return REGISTRY.get(bulletin_name.strip().upper())
