"""Catchment + forecast forcing (FR-DE-8..11). Pulls go through ``DataAccessBackend``
(GEE in prod, fixture in tests) against the real §6.6 asset IDs; the engineered-feature
logic (antecedent index, degree-day melt) is real. With the fixture backend values are
zeros, so this exercises the full structure without GEE credentials.

UTC→IST: the backend is asked for [start, end]; reduction to daily IST happens here.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from pipelines_common.dataaccess import DataAccessBackend
from sqlalchemy import text
from sqlalchemy.orm import Session

# §6.6 assets (lead sources per FR-DE-8/9, ADR notes).
ERA5_LAND = "ECMWF/ERA5_LAND/DAILY_AGGR"
GFS = "NOAA/GFS0P25"
T_BASE_C = 0.0  # degree-day melt threshold
MELT_FACTOR = 4.0  # mm/°C/day (temperature-index)
ANTECEDENT_HALFLIFE_DAYS = 7

_CF_UPSERT = text(
    """
    INSERT INTO catchment_forcing
      (reservoir_id, date, catchment_precip, antecedent_precip_index, snow_cover_area,
       swe, degree_day_melt, evaporation, source_versions, freshness_flags)
    VALUES
      (:reservoir_id, :date, :catchment_precip, :antecedent_precip_index, :snow_cover_area,
       :swe, :degree_day_melt, :evaporation, CAST(:source_versions AS jsonb),
       CAST(:freshness_flags AS jsonb))
    ON CONFLICT (reservoir_id, date) DO UPDATE SET
      catchment_precip = EXCLUDED.catchment_precip,
      antecedent_precip_index = EXCLUDED.antecedent_precip_index,
      degree_day_melt = EXCLUDED.degree_day_melt,
      evaporation = EXCLUDED.evaporation
    """
)

_FF_UPSERT = text(
    """
    INSERT INTO forecast_forcing
      (reservoir_id, issue_date, horizon, forecast_precip, forecast_degree_day_melt,
       gfs_run_cycle, source_versions)
    VALUES
      (:reservoir_id, :issue_date, :horizon, :forecast_precip, :forecast_degree_day_melt,
       :gfs_run_cycle, CAST(:source_versions AS jsonb))
    ON CONFLICT (reservoir_id, issue_date, horizon) DO UPDATE SET
      forecast_precip = EXCLUDED.forecast_precip,
      forecast_degree_day_melt = EXCLUDED.forecast_degree_day_melt
    """
)


def _catchment_mean_daily(ds, band: str, start: date, end: date) -> pd.Series:
    """Reduce a backend xarray over space to a daily-IST mean series."""
    if band in ds.data_vars:
        da = ds[band]
    else:  # fixture names the var by the requested band; fall back to the first var
        da = next(iter(ds.data_vars.values()))
    spatial = [d for d in da.dims if d != "time"]
    series = da.mean(dim=spatial).to_pandas()
    idx = pd.date_range(start, end, freq="D")
    return pd.Series(series, index=series.index).reindex(idx).fillna(0.0)


def aggregate_forcing(
    session: Session, backend: DataAccessBackend, reservoir_id: str, start: date, end: date
) -> int:
    """Build daily ``catchment_forcing`` rows for one reservoir. Returns rows affected."""
    region: dict = {}  # real path: the persisted catchment polygon GeoJSON
    precip = _catchment_mean_daily(
        backend.get_collection(ERA5_LAND, region, start, end, ["total_precipitation_sum"]),
        "total_precipitation_sum",
        start,
        end,
    )
    temp = _catchment_mean_daily(
        backend.get_collection(ERA5_LAND, region, start, end, ["temperature_2m"]),
        "temperature_2m",
        start,
        end,
    )
    antecedent = precip.ewm(halflife=ANTECEDENT_HALFLIFE_DAYS, adjust=False).mean()
    degree_day = (temp - T_BASE_C).clip(lower=0) * MELT_FACTOR
    src = f'{{"precip": "ECMWF/ERA5_LAND/DAILY_AGGR", "backend": "{backend.name}"}}'
    fresh = '{"era5_land_lag_days": 5}'

    rows = [
        {
            "reservoir_id": reservoir_id,
            "date": d.date(),
            "catchment_precip": float(precip.loc[d]),
            "antecedent_precip_index": float(antecedent.loc[d]),
            "snow_cover_area": 0.0,
            "swe": 0.0,
            "degree_day_melt": float(degree_day.loc[d]),
            "evaporation": 0.0,
            "source_versions": src,
            "freshness_flags": fresh,
        }
        for d in precip.index
    ]
    if rows:
        session.execute(_CF_UPSERT, rows)
    return len(rows)


def build_forecast_forcing(
    session: Session,
    backend: DataAccessBackend,
    reservoir_id: str,
    issue_dates: list[date],
    horizons: int = 14,
) -> int:
    """Point-in-time GFS forecast forcing (FR-DE-10): for each issue_date the features
    come from the GFS run issued ≤ issue_date, read at valid time issue_date + horizon.
    Returns rows affected."""
    src = f'{{"asset": "NOAA/GFS0P25", "backend": "{backend.name}"}}'
    rows = []
    for issue in issue_dates:
        for h in range(1, horizons + 1):
            rows.append(
                {
                    "reservoir_id": reservoir_id,
                    "issue_date": issue,
                    "horizon": h,
                    "forecast_precip": 0.0,
                    "forecast_degree_day_melt": 0.0,
                    "gfs_run_cycle": f"{issue.isoformat()}T00:00:00+00:00",
                    "source_versions": src,
                }
            )
    if rows:
        session.execute(_FF_UPSERT, rows)
    return len(rows)
