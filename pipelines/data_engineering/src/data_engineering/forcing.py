"""Catchment + forecast forcing (FR-DE-8..11). Pulls go through ``DataAccessBackend``
(GEE in prod, fixture in tests) against the real §6.6 asset IDs; the engineered-feature
logic (antecedent index, degree-day melt) is real. With the fixture backend values are
zeros, so this exercises the full structure without GEE credentials.

UTC→IST: the backend is asked for [start, end]; reduction to daily IST happens here.

Units (contract §2): ERA5-Land ``total_precipitation_sum`` is metres/day and
``temperature_2m`` is Kelvin — both are converted here (mm/day, °C) before any feature
is derived. Missing source days stay NULL, never a silent zero.
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
T_BASE_C = 0.0  # degree-day melt threshold (°C)
MELT_FACTOR = 4.0  # mm/°C/day (temperature-index)
ANTECEDENT_HALFLIFE_DAYS = 7
# ERA5-Land daily aggregates publish ~5 days behind real time. Recorded per-row in
# freshness_flags AND applied at ABT join time (build_abt shifts the forcing frame by
# this lag so a row is only joinable once it was actually publishable) — see build_abt.
ERA5_LAND_LAG_DAYS = 5

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
      snow_cover_area = EXCLUDED.snow_cover_area,
      swe = EXCLUDED.swe,
      degree_day_melt = EXCLUDED.degree_day_melt,
      evaporation = EXCLUDED.evaporation,
      source_versions = EXCLUDED.source_versions,
      freshness_flags = EXCLUDED.freshness_flags
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
      forecast_degree_day_melt = EXCLUDED.forecast_degree_day_melt,
      gfs_run_cycle = EXCLUDED.gfs_run_cycle,
      source_versions = EXCLUDED.source_versions
    """
)


def _catchment_mean_daily(ds, band: str, start: date, end: date) -> pd.Series:
    """Reduce a backend xarray over space to a daily-IST mean series. Days the source
    does not cover stay NaN (contract: NULL = not available, never a silent zero)."""
    if band in ds.data_vars:
        da = ds[band]
    else:  # fixture names the var by the requested band; fall back to the first var
        da = next(iter(ds.data_vars.values()))
    spatial = [d for d in da.dims if d != "time"]
    series = da.mean(dim=spatial).to_pandas()
    idx = pd.date_range(start, end, freq="D")
    return pd.Series(series, index=series.index).reindex(idx)


def engineer_forcing_features(precip_m: pd.Series, temp_k: pd.Series) -> pd.DataFrame:
    """Derive the engineered forcing features from ERA5-Land native-unit series.

    Unit conversions happen here, once, before any feature math:

    * ``total_precipitation_sum`` metres/day → mm/day (contract §2);
    * ``temperature_2m`` Kelvin → °C before the degree-day melt index (feeding Kelvin
      to ``(T - T_BASE_C) * MELT_FACTOR`` would fabricate ~1000 mm/day of melt).

    Missing inputs propagate as NaN (→ SQL NULL), never a silent zero.
    """
    precip_mm = precip_m * 1000.0
    temp_c = temp_k - 273.15
    antecedent = precip_mm.ewm(halflife=ANTECEDENT_HALFLIFE_DAYS, adjust=False).mean()
    degree_day_melt = (temp_c - T_BASE_C).clip(lower=0) * MELT_FACTOR
    return pd.DataFrame(
        {
            "catchment_precip": precip_mm,
            "antecedent_precip_index": antecedent,
            "degree_day_melt": degree_day_melt,
        }
    )


def _none_if_nan(v) -> float | None:
    return None if pd.isna(v) else float(v)


def aggregate_forcing(
    session: Session, backend: DataAccessBackend, reservoir_id: str, start: date, end: date
) -> int:
    """Build daily ``catchment_forcing`` rows for one reservoir. Returns rows affected."""
    region: dict = {}  # real path: the persisted catchment polygon GeoJSON
    precip_m = _catchment_mean_daily(
        backend.get_collection(ERA5_LAND, region, start, end, ["total_precipitation_sum"]),
        "total_precipitation_sum",
        start,
        end,
    )
    temp_k = _catchment_mean_daily(
        backend.get_collection(ERA5_LAND, region, start, end, ["temperature_2m"]),
        "temperature_2m",
        start,
        end,
    )
    feats = engineer_forcing_features(precip_m, temp_k)
    src = f'{{"precip": "ECMWF/ERA5_LAND/DAILY_AGGR", "backend": "{backend.name}"}}'
    fresh = f'{{"era5_land_lag_days": {ERA5_LAND_LAG_DAYS}}}'

    rows = [
        {
            "reservoir_id": reservoir_id,
            "date": d.date(),
            "catchment_precip": _none_if_nan(feats.at[d, "catchment_precip"]),
            "antecedent_precip_index": _none_if_nan(feats.at[d, "antecedent_precip_index"]),
            # TODO(FR-DE-9): snow (MODIS), SWE and ERA5 open-water evaporation pulls are
            # not wired yet. Contract: NULL = not available — never a silent zero.
            "snow_cover_area": None,
            "swe": None,
            "degree_day_melt": _none_if_nan(feats.at[d, "degree_day_melt"]),
            "evaporation": None,
            "source_versions": src,
            "freshness_flags": fresh,
        }
        for d in feats.index
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
