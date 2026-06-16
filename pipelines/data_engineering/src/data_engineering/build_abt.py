"""ABT builder (FR-DE-12, FR-ABT-1..5, AC-10) — the gold output.

One row per ``(reservoir_id, date)`` on a continuous daily IST calendar. Ground-truth and
SAR columns are populated only on their exact dates (sparse); ``days_since_*`` recency
comes from a strictly **backward** as-of match, so no future value ever reaches a past row
(the leakage guarantee). Forecast forcing is NOT denormalised here (contract v2/v3) — ML
joins ``forecast_forcing`` on ``issue_date = date``.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

_STALE = 9999  # days_since_* sentinel when no prior observation exists yet


def _na_to_none(v):
    """NaN/NaT/None → None (so psycopg writes SQL NULL, not the float 'NaN')."""
    try:
        return None if pd.isna(v) else v
    except (TypeError, ValueError):  # arrays / unhashable → leave as-is
        return v


_ABT_UPSERT = text(
    """
    INSERT INTO analytical_base_table (
        reservoir_id, date, abt_version, days_since_bulletin, days_since_acquisition,
        gt_level, gt_live_storage_bcm, gt_pct_filled, frl, live_capacity_bcm,
        normal_storage_pct, surface_area, area_confidence, derived_volume, derived_level,
        extraction_method, catchment_precip, antecedent_precip_index, snow_cover_area,
        swe, degree_day_melt, evaporation, is_extrapolated, residual_vs_ground_truth,
        source_versions, freshness_flags, row_quality
    ) VALUES (
        :reservoir_id, :date, :abt_version, :days_since_bulletin, :days_since_acquisition,
        :gt_level, :gt_live_storage_bcm, :gt_pct_filled, :frl, :live_capacity_bcm,
        :normal_storage_pct, :surface_area, :area_confidence, :derived_volume, :derived_level,
        :extraction_method, :catchment_precip, :antecedent_precip_index, :snow_cover_area,
        :swe, :degree_day_melt, :evaporation, :is_extrapolated, :residual_vs_ground_truth,
        CAST(:source_versions AS jsonb), CAST(:freshness_flags AS jsonb), :row_quality
    )
    ON CONFLICT (reservoir_id, date, abt_version) DO UPDATE SET
        gt_pct_filled = EXCLUDED.gt_pct_filled,
        surface_area = EXCLUDED.surface_area,
        days_since_bulletin = EXCLUDED.days_since_bulletin,
        days_since_acquisition = EXCLUDED.days_since_acquisition
    """
)


def _backward_recency(spine: pd.DataFrame, event_dates: pd.Series) -> pd.Series:
    """Days since the most-recent event date ≤ each spine date (backward as-of)."""
    if event_dates.empty:
        return pd.Series([_STALE] * len(spine), index=spine.index)
    ev = pd.DataFrame({"date": pd.to_datetime(sorted(event_dates.unique()))})
    ev["event_date"] = ev["date"]
    merged = pd.merge_asof(spine.sort_values("date"), ev, on="date", direction="backward")
    days = (merged["date"] - merged["event_date"]).dt.days
    return days.fillna(_STALE).astype(int)


def build_abt_for_reservoir(session: Session, reservoir_id: str, abt_version: str) -> int:
    """Build + upsert the ABT for one reservoir. Returns rows written."""
    conn = session.connection()
    res = conn.execute(
        text("SELECT frl_m, live_capacity_bcm FROM reservoir WHERE reservoir_id = :r"),
        {"r": reservoir_id},
    ).one()
    frl, capacity = float(res[0]), float(res[1])

    gt = pd.read_sql(
        text(
            "SELECT date, level_m AS gt_level, live_storage_bcm AS gt_live_storage_bcm, "
            "pct_filled AS gt_pct_filled, normal_storage_pct, row_quality "
            "FROM ground_truth WHERE reservoir_id = :r AND row_quality <> 'quarantine'"
        ),
        conn,
        params={"r": reservoir_id},
        parse_dates=["date"],
    )
    obs = pd.read_sql(
        text(
            "SELECT acquisition_date AS date, surface_area, area_confidence, "
            "derived_volume, derived_level, extraction_method "
            "FROM observation WHERE reservoir_id = :r"
        ),
        conn,
        params={"r": reservoir_id},
        parse_dates=["date"],
    )
    forcing = pd.read_sql(
        text(
            "SELECT date, catchment_precip, antecedent_precip_index, snow_cover_area, "
            "swe, degree_day_melt, evaporation FROM catchment_forcing WHERE reservoir_id = :r"
        ),
        conn,
        params={"r": reservoir_id},
        parse_dates=["date"],
    )

    anchors = pd.concat([gt["date"], obs["date"], forcing["date"]])
    if anchors.empty:
        return 0
    spine = pd.DataFrame({"date": pd.date_range(anchors.min(), anchors.max(), freq="D")})

    df = (
        spine.merge(gt, on="date", how="left")
        .merge(obs, on="date", how="left")
        .merge(forcing, on="date", how="left")
    )
    df["days_since_bulletin"] = _backward_recency(spine, gt["date"])
    df["days_since_acquisition"] = _backward_recency(spine, obs["date"])
    df["reservoir_id"] = reservoir_id
    df["abt_version"] = abt_version
    df["frl"] = frl
    df["live_capacity_bcm"] = capacity
    df["is_extrapolated"] = False  # pre-curve; set in Pass-2 (§5.6)
    df["residual_vs_ground_truth"] = None
    df["row_quality"] = df["row_quality"].fillna("ok")
    df["source_versions"] = '{"abt_builder": "v0"}'
    df["freshness_flags"] = "{}"

    records = []
    for _, r in df.iterrows():
        rec = {k: _na_to_none(v) for k, v in r.to_dict().items()}
        rec["date"] = pd.Timestamp(r["date"]).date()
        records.append(rec)
    session.execute(_ABT_UPSERT, records)
    return len(records)


def build_abt(session: Session, reservoir_ids: list[str], abt_version: str) -> int:
    total = 0
    for rid in reservoir_ids:
        total += build_abt_for_reservoir(session, rid, abt_version)
    return total
