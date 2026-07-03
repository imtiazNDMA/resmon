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

from data_engineering.forcing import ERA5_LAND_LAG_DAYS

_STALE = 9999  # days_since_* sentinel when no prior observation exists yet


def _shift_to_available(forcing: pd.DataFrame, lag_days: int = ERA5_LAND_LAG_DAYS) -> pd.DataFrame:
    """Re-key the forcing frame from event time to information-set time (A4).

    ERA5-Land daily aggregates publish ~``lag_days`` behind real time, so the forcing
    measured on event date ``d`` is only knowable from ``d + lag_days``. The ABT is
    point-in-time ("every column holds only what was knowable at date"), so the join
    key is shifted forward by the lag: the ABT row at date ``t`` carries the most
    recent *published* forcing (event date ``t - lag_days``). This also keeps
    ``antecedent_precip_index`` honest — its EWM window never includes precipitation
    that was not yet published at ``t``.
    """
    shifted = forcing.copy()
    shifted["date"] = shifted["date"] + pd.Timedelta(days=lag_days)
    return shifted


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
        days_since_bulletin = EXCLUDED.days_since_bulletin,
        days_since_acquisition = EXCLUDED.days_since_acquisition,
        gt_level = EXCLUDED.gt_level,
        gt_live_storage_bcm = EXCLUDED.gt_live_storage_bcm,
        gt_pct_filled = EXCLUDED.gt_pct_filled,
        frl = EXCLUDED.frl,
        live_capacity_bcm = EXCLUDED.live_capacity_bcm,
        normal_storage_pct = EXCLUDED.normal_storage_pct,
        surface_area = EXCLUDED.surface_area,
        area_confidence = EXCLUDED.area_confidence,
        derived_volume = EXCLUDED.derived_volume,
        derived_level = EXCLUDED.derived_level,
        extraction_method = EXCLUDED.extraction_method,
        catchment_precip = EXCLUDED.catchment_precip,
        antecedent_precip_index = EXCLUDED.antecedent_precip_index,
        snow_cover_area = EXCLUDED.snow_cover_area,
        swe = EXCLUDED.swe,
        degree_day_melt = EXCLUDED.degree_day_melt,
        evaporation = EXCLUDED.evaporation,
        is_extrapolated = EXCLUDED.is_extrapolated,
        residual_vs_ground_truth = EXCLUDED.residual_vs_ground_truth,
        source_versions = EXCLUDED.source_versions,
        freshness_flags = EXCLUDED.freshness_flags,
        row_quality = EXCLUDED.row_quality
    """
)


def _backward_recency(spine: pd.DataFrame, event_dates: pd.Series) -> pd.Series:
    """Days since the most-recent event date ≤ each spine date (backward as-of)."""
    if event_dates.empty:
        return pd.Series([_STALE] * len(spine), index=spine.index)
    # merge_asof requires identical key dtypes; SQL DATE columns parse to datetime64[s]
    # while the date_range spine is a finer resolution, so pin both to [ns].
    ev = pd.DataFrame(
        {"date": pd.to_datetime(sorted(event_dates.unique())).astype("datetime64[ns]")}
    )
    ev["event_date"] = ev["date"]
    left = spine.sort_values("date").astype({"date": "datetime64[ns]"})
    merged = pd.merge_asof(left, ev, on="date", direction="backward")
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
    # ERA5 publication latency: join forcing at the date it became knowable, not the
    # event date (see _shift_to_available).
    forcing = _shift_to_available(forcing)

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
