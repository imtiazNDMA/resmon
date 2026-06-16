"""Data-validation suite (FR-DE-4, NFR-TEST-1, AC-12). pandera schemas applied at the
silver/gold boundaries; failing rows are quarantined upstream, never silently propagated.
"""

from __future__ import annotations

try:  # pandera ≥ 0.24 moved the pandas API under pandera.pandas
    from pandera.pandas import Check, Column, DataFrameSchema
except ImportError:  # pragma: no cover - older pandera
    from pandera import Check, Column, DataFrameSchema

import pandas as pd

# Non-quarantine bulletins: fill in band, level/frl sane.
BULLETIN_SCHEMA = DataFrameSchema(
    {
        "reservoir_id": Column(str, nullable=False),
        "pct_filled": Column(float, Check.in_range(0, 110), nullable=True),
        "level_m": Column(float, Check.ge(0), nullable=True),
        "frl_m": Column(float, Check.gt(0), nullable=False),
        "live_capacity_bcm": Column(float, Check.gt(0), nullable=False),
    },
    strict=False,
    coerce=True,
)

# Gold ABT: static FRL/capacity non-null; derived/observed within physical bounds.
ABT_SCHEMA = DataFrameSchema(
    {
        "reservoir_id": Column(str, nullable=False),
        "frl": Column(float, nullable=False),
        "live_capacity_bcm": Column(float, nullable=False),
        "gt_pct_filled": Column(float, Check.in_range(0, 110), nullable=True),
        "surface_area": Column(float, Check.ge(0), nullable=True),
        "row_quality": Column(str, Check.isin(["ok", "low_confidence", "quarantine"])),
    },
    strict=False,
    coerce=True,
    unique=["reservoir_id", "date"],
)


def validate_bulletins(df: pd.DataFrame) -> pd.DataFrame:
    """Validate the clean (``row_quality == 'ok'``) bulletin frame; raises on schema error.
    ``low_confidence`` / ``quarantine`` rows are carried with their flag, not hard-failed."""
    clean = df[df["row_quality"] == "ok"]
    return BULLETIN_SCHEMA.validate(clean, lazy=True)


def validate_abt(df: pd.DataFrame) -> pd.DataFrame:
    """Validate a built ABT frame (one abt_version); raises on schema error."""
    return ABT_SCHEMA.validate(df, lazy=True)


__all__ = ["BULLETIN_SCHEMA", "ABT_SCHEMA", "validate_bulletins", "validate_abt"]
