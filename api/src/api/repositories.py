"""Read repositories — SQL queries behind the API (FR-API-1/2). Read-only; the serving
layer never writes (NFR-SEC-3). All return plain dicts/rows; the routes' Pydantic
response models (D5) handle type coercion (e.g. Postgres ``numeric`` → JSON number).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from core.config import get_settings
from sqlalchemy import text
from sqlalchemy.orm import Session

# The data is on an IST calendar (bulletin dates, SAR acquisition dates); staleness
# must be measured against the IST "today", not the server's local clock (D9).
_IST = ZoneInfo("Asia/Kolkata")

# Bound the public GeoJSON surface (D4): simplify to ~10 m tolerance and cap
# coordinate precision at 5 decimal digits (~1 m) so payloads stay small.
_SIMPLIFY_TOLERANCE_DEG = 0.0001
_MAX_DECIMAL_DIGITS = 5

# C5 provenance (mirrors ml.forecasting/ml.gate): the demo bootstrap writes synthetic
# observations stamped with the REAL extractor name, so `<> 'stub'` alone is not enough
# — synthetic rows are marked by their scene_ids. Serving paths must never present a
# synthetic area, mint a tile for a fake scene, or let one freshen the staleness clock.
_REAL_OBS = (
    "extraction_method <> 'stub' AND NOT ('synthetic' = ANY(scene_ids) OR 'stub' = ANY(scene_ids))"
)


def _polyval(coeffs: list[float] | None, x: float) -> float | None:
    if not coeffs:
        return None
    y = 0.0
    for coeff in coeffs:
        y = y * x + float(coeff)
    return y


def _with_curve_estimate(row, *, fill_missing: bool = True) -> dict:
    out = dict(row)
    area = out.get("area_km2")
    observed_range = out.get("observed_range") or {}
    out["is_extrapolated"] = False
    if area is not None and observed_range:
        area_min = observed_range.get("area_min")
        area_max = observed_range.get("area_max")
        out["is_extrapolated"] = (
            (area_min is not None and float(area) < float(area_min))
            or (area_max is not None and float(area) > float(area_max))
        )
    if fill_missing and out.get("live_storage_bcm") is None and area is not None:
        out["live_storage_bcm"] = _polyval(out.get("storage_coeffs"), float(area))
    if fill_missing and out.get("level_m") is None and area is not None:
        out["level_m"] = _polyval(out.get("level_coeffs"), float(area))
    if fill_missing and out.get("pct_filled") is None and out.get("live_storage_bcm") is not None:
        capacity = out.get("live_capacity_bcm")
        if capacity:
            out["pct_filled"] = float(out["live_storage_bcm"]) / float(capacity) * 100.0
    out.pop("storage_coeffs", None)
    out.pop("level_coeffs", None)
    out.pop("live_capacity_bcm", None)
    out.pop("observed_range", None)
    return out


def list_reservoirs(s: Session) -> list[dict]:
    rows = (
        s.execute(
            text(
                "SELECT reservoir_id, name, basin, frl_m, live_capacity_bcm, is_active "
                "FROM reservoir ORDER BY reservoir_id"
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def get_reservoir(s: Session, rid: str) -> dict | None:
    row = (
        s.execute(
            text(
                "SELECT reservoir_id, name, basin, frl_m, live_capacity_bcm, orbit_relative, "
                "pass_direction, aoi_version, is_active FROM reservoir WHERE reservoir_id = :r"
            ),
            {"r": rid},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def latest_status(s: Session, rid: str) -> dict | None:
    est = current_estimate(s, rid)
    obs = (
        {
            "date": est["acquisition_date"],
            "pct_filled": est["pct_filled"],
            "level_m": est["level_m"],
            "live_storage_bcm": est["live_storage_bcm"],
        }
        if est
        else None
    )
    gt = (
        s.execute(
            text(
                "SELECT gt.date, gt.level_m, gt.live_storage_bcm, "
                "       gt.live_storage_bcm / NULLIF(r.live_capacity_bcm, 0) * 100 AS pct_filled "
                "FROM ground_truth gt JOIN reservoir r ON r.reservoir_id = gt.reservoir_id "
                "WHERE gt.reservoir_id = :r AND gt.live_storage_bcm IS NOT NULL "
                "ORDER BY gt.date DESC LIMIT 1"
            ),
            {"r": rid},
        )
        .mappings()
        .first()
    )
    # The dashboard displays the historical bulletin value when available; a curve
    # estimate is only the fallback when the bootstrap corpus has no matching state.
    state = gt or obs
    if state is None:
        return None
    risk = (
        s.execute(
            text(
                "SELECT risk_level, release_probability, estimated_lead_time_days, run_timestamp "
                "FROM release_risk WHERE reservoir_id = :r ORDER BY run_timestamp DESC LIMIT 1"
            ),
            {"r": rid},
        )
        .mappings()
        .first()
    )
    last_acq = s.execute(
        text(
            f"SELECT max(acquisition_date) FROM observation WHERE reservoir_id = :r AND {_REAL_OBS}"
        ),
        {"r": rid},
    ).scalar()
    # Graceful-degradation / staleness (NFR-REL-6, D8): age from the freshest signal
    # (SAR acquisition if any, else the latest bulletin), measured on the IST calendar.
    threshold = get_settings().data_staleness_threshold_days
    ref = last_acq or state["date"]
    age_days = (datetime.now(_IST).date() - ref).days if ref is not None else None
    # Unknown age is still a well-formed payload: stale=true, age null (D9).
    return {
        "reservoir_id": rid,
        "as_of": state["date"],
        "pct_filled": state["pct_filled"],
        "level_m": state["level_m"],
        "live_storage_bcm": state["live_storage_bcm"],
        "risk_level": risk["risk_level"] if risk else None,
        "release_probability": risk["release_probability"] if risk else None,
        "estimated_lead_time_days": risk["estimated_lead_time_days"] if risk else None,
        "last_acquisition_date": last_acq,
        "data_age_days": age_days,
        "stale": age_days is None or age_days > threshold,
    }


def timeseries(s: Session, rid: str, limit: int) -> list[dict]:
    rows = (
        s.execute(
            text(
                "SELECT date, pct_filled, level_m, live_storage_bcm, normal_storage_pct "
                "FROM ground_truth WHERE reservoir_id = :r AND pct_filled IS NOT NULL "
                "ORDER BY date DESC LIMIT :n"
            ),
            {"r": rid, "n": limit},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in reversed(rows)]


def latest_forecast(s: Session, rid: str) -> list[dict]:
    latest = s.execute(
        text("SELECT max(run_timestamp) FROM prediction WHERE reservoir_id = :r"),
        {"r": rid},
    ).scalar()
    if latest is None:
        return []
    rows = (
        s.execute(
            text(
                "SELECT horizon_date, predicted_pct_filled, interval_low, interval_high "
                "FROM prediction WHERE reservoir_id = :r AND run_timestamp = :t "
                "ORDER BY horizon_date"
            ),
            {"r": rid, "t": latest},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def fleet_release_risk(s: Session) -> list[dict]:
    rows = (
        s.execute(
            text(
                """
            SELECT DISTINCT ON (reservoir_id)
                reservoir_id, risk_level, release_probability, estimated_lead_time_days,
                run_timestamp
            FROM release_risk
            ORDER BY reservoir_id, run_timestamp DESC
            """
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def accuracy(s: Session) -> dict:
    curves = (
        s.execute(
            text(
                "SELECT reservoir_id, version, fit_metrics FROM rating_curve WHERE is_active "
                "ORDER BY reservoir_id"
            )
        )
        .mappings()
        .all()
    )
    forecaster = (
        s.execute(
            text(
                "SELECT version, metrics FROM model_version WHERE model_name = 'forecaster' "
                "ORDER BY created_at DESC LIMIT 1"
            )
        )
        .mappings()
        .first()
    )
    return {
        "rating_curves": [dict(c) for c in curves],
        "forecaster": dict(forecaster) if forecaster else None,
        "note": "Accuracy is a historical backtest; with synthetic SAR/forcing it is a "
        "machinery check, not real extraction/forecast accuracy (needs live GEE).",
    }


def acquisitions(s: Session, rid: str) -> list[dict]:
    """Non-stub SAR acquisition series for the timeline (dashboard spec endpoint 1)."""
    rows = (
        s.execute(
            text(
                "SELECT o.acquisition_date::text AS date, o.surface_area, o.area_confidence, "
                "       hist.historical_date, hist.live_storage_bcm, hist.level_m, "
                "       hist.live_storage_bcm / NULLIF(r.live_capacity_bcm, 0) * 100 "
                "         AS pct_filled, "
                "       corr.area_storage_correlation, "
                "       r.live_capacity_bcm, "
                "       rc.area_to_storage_params->'coeffs' AS storage_coeffs, "
                "       rc.area_to_level_params->'coeffs' AS level_coeffs, "
                "       rc.observed_range AS observed_range "
                "FROM observation o "
                "JOIN reservoir r ON r.reservoir_id = o.reservoir_id "
                "LEFT JOIN rating_curve rc ON rc.reservoir_id = o.reservoir_id AND rc.is_active "
                "LEFT JOIN LATERAL ( "
                "  SELECT gt.date::text AS historical_date, gt.live_storage_bcm, gt.level_m "
                "  FROM ground_truth gt "
                "  WHERE gt.reservoir_id = o.reservoir_id "
                "    AND gt.live_storage_bcm IS NOT NULL AND gt.row_quality <> 'quarantine' "
                "    AND abs(gt.date - o.acquisition_date) <= 5 "
                "  ORDER BY abs(gt.date - o.acquisition_date), gt.date DESC LIMIT 1 "
                ") hist ON true "
                "LEFT JOIN LATERAL ( "
                "  SELECT corr(m.extracted_area, g.live_storage_bcm) AS area_storage_correlation "
                "  FROM ground_truth_match m "
                "  JOIN ground_truth g ON g.reservoir_id = m.reservoir_id AND g.date = m.gt_date "
                "  WHERE m.reservoir_id = o.reservoir_id AND m.extracted_area IS NOT NULL "
                "    AND m.extraction_method <> 'stub' "
                "    AND NOT ('synthetic' = ANY(m.scene_ids) OR 'stub' = ANY(m.scene_ids)) "
                ") corr ON true "
                f"WHERE o.reservoir_id = :r AND {_REAL_OBS} "
                "ORDER BY o.acquisition_date"
            ),
            {"r": rid},
        )
        .mappings()
        .all()
    )
    return [
        _with_curve_estimate(
            {
                "date": r["date"],
                "area_km2": r["surface_area"],
                "confidence": r["area_confidence"],
                "live_storage_bcm": r["live_storage_bcm"],
                "level_m": r["level_m"],
                "pct_filled": r["pct_filled"],
                "historical_date": r["historical_date"],
                "surface_area_correlation": r["area_storage_correlation"],
                "live_capacity_bcm": r["live_capacity_bcm"],
                "storage_coeffs": r["storage_coeffs"],
                "level_coeffs": r["level_coeffs"],
                "observed_range": r["observed_range"],
            },
            fill_missing=False,
        )
        for r in rows
    ]


def current_estimate(s: Session, rid: str, date: str | None = None) -> dict | None:
    """Current-state estimate for a SAR acquisition: imagery area -> storage/level/fill."""
    date_filter = "AND o.acquisition_date = :d" if date is not None else ""
    row = (
        s.execute(
            text(
                f"""
                SELECT o.reservoir_id,
                       o.acquisition_date::text AS acquisition_date,
                       o.surface_area AS area_km2,
                       o.area_confidence AS confidence,
                       o.derived_volume AS live_storage_bcm,
                       o.derived_level AS level_m,
                       o.derived_volume / NULLIF(r.live_capacity_bcm, 0) * 100 AS pct_filled,
                       r.live_capacity_bcm,
                       rc.version AS rating_curve_version,
                       rc.fit_type AS rating_curve_fit_type,
                       rc.area_to_storage_params->'coeffs' AS storage_coeffs,
                       rc.area_to_level_params->'coeffs' AS level_coeffs,
                       rc.observed_range AS observed_range,
                       cf.catchment_precip,
                       cf.antecedent_precip_index,
                       cf.snow_cover_area,
                       cf.degree_day_melt,
                       cf.evaporation
                FROM observation o
                JOIN reservoir r ON r.reservoir_id = o.reservoir_id
                LEFT JOIN rating_curve rc ON rc.reservoir_id = o.reservoir_id AND rc.is_active
                LEFT JOIN catchment_forcing cf
                  ON cf.reservoir_id = o.reservoir_id AND cf.date = o.acquisition_date
                WHERE o.reservoir_id = :r {date_filter}
                  AND extraction_method <> 'stub'
                  AND NOT ('synthetic' = ANY(scene_ids) OR 'stub' = ANY(scene_ids))
                ORDER BY o.acquisition_date DESC
                LIMIT 1
                """
            ),
            {"r": rid, "d": date},
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    out = _with_curve_estimate(row)
    if out["live_storage_bcm"] is None or out["level_m"] is None or out["pct_filled"] is None:
        return None
    return out


def scene_id_for_date(s: Session, rid: str, date: str) -> str | None:
    """First scene id behind the (reservoir, date) observation, for tile minting."""
    row = s.execute(
        text(
            "SELECT scene_ids FROM observation "
            "WHERE reservoir_id = :r AND acquisition_date = :d "
            f"AND {_REAL_OBS}"
        ),
        {"r": rid, "d": date},
    ).fetchone()
    return row.scene_ids[0] if row and row.scene_ids else None


def rainfall(s: Session, rid: str, window_days: int) -> list[dict]:
    """Catchment precipitation over the trailing window (dashboard spec endpoint 3).

    Empty until live forcing ingest lands — the frontend renders that honestly
    ("awaiting live forcing"), never fake zeros.
    """
    rows = (
        s.execute(
            text(
                "SELECT date::text AS date, catchment_precip AS precip_mm "
                "FROM catchment_forcing "
                "WHERE reservoir_id = :r AND date >= CURRENT_DATE - :w * INTERVAL '1 day' "
                "ORDER BY date"
            ),
            {"r": rid, "w": window_days},
        )
        .mappings()
        .all()
    )
    return [{"date": r["date"], "precip_mm": r["precip_mm"]} for r in rows]


def met_forcings(s: Session, rid: str) -> dict:
    """Latest catchment-aggregated meteorological forcings for map overlays."""
    row = (
        s.execute(
            text(
                """
                WITH latest AS (
                    SELECT * FROM catchment_forcing
                    WHERE reservoir_id = :r
                    ORDER BY date DESC
                    LIMIT 1
                ), precip AS (
                    SELECT sum(catchment_precip) AS precip_7d_mm
                    FROM catchment_forcing
                    WHERE reservoir_id = :r
                      AND date >= (SELECT date FROM latest) - INTERVAL '6 days'
                      AND date <= (SELECT date FROM latest)
                )
                SELECT
                    latest.reservoir_id,
                    latest.date::text AS as_of,
                    precip.precip_7d_mm,
                    latest.antecedent_precip_index AS antecedent_precip_index_mm,
                    latest.snow_cover_area * 100 AS snow_cover_pct,
                    latest.degree_day_melt AS degree_day_melt_mm_day,
                    latest.evaporation AS evaporation_mm_day
                FROM latest CROSS JOIN precip
                """
            ),
            {"r": rid},
        )
        .mappings()
        .first()
    )
    if row is None:
        return {
            "reservoir_id": rid,
            "as_of": None,
            "precip_7d_mm": None,
            "antecedent_precip_index_mm": None,
            "snow_cover_pct": None,
            "degree_day_melt_mm_day": None,
            "evaporation_mm_day": None,
        }
    return dict(row)


def _bounded_geojson(geom_expr: str) -> str:
    """SQL for topology-preserving simplification + capped precision (D4)."""
    return (
        f"ST_AsGeoJSON(ST_SimplifyPreserveTopology({geom_expr}, {_SIMPLIFY_TOLERANCE_DEG}), "
        f"{_MAX_DECIMAL_DIGITS})"
    )


def aoi_features(s: Session) -> list[dict]:
    rows = (
        s.execute(
            text(
                f"SELECT reservoir_id, name, aoi_version, {_bounded_geojson('aoi_geom')} AS g "
                "FROM reservoir WHERE aoi_geom IS NOT NULL ORDER BY reservoir_id"
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def catchment_features(s: Session) -> list[dict]:
    rows = (
        s.execute(
            text(
                "SELECT reservoir_id, name, catchment_version, "
                f"{_bounded_geojson('catchment_geom')} AS g "
                "FROM reservoir WHERE catchment_geom IS NOT NULL ORDER BY reservoir_id"
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def water_extent_features(s: Session) -> list[dict]:
    rows = (
        s.execute(
            text(
                f"""
            SELECT DISTINCT ON (o.reservoir_id)
                o.reservoir_id, r.name, o.surface_area, o.acquisition_date,
                {_bounded_geojson("o.water_mask_geom")} AS g
            FROM observation o
            JOIN reservoir r ON r.reservoir_id = o.reservoir_id
            WHERE o.water_mask_geom IS NOT NULL AND {_REAL_OBS}
            ORDER BY o.reservoir_id, o.acquisition_date DESC
            """
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def reservoir_features(s: Session) -> list[dict]:
    rows = (
        s.execute(
            text(
                f"""
            SELECT r.reservoir_id, r.name, r.frl_m,
                   ST_AsGeoJSON(r.dam_point, {_MAX_DECIMAL_DIGITS}) AS dam_point_geojson,
                   rr.risk_level, rr.release_probability
            FROM reservoir r
            LEFT JOIN LATERAL (
                SELECT risk_level, release_probability FROM release_risk
                WHERE reservoir_id = r.reservoir_id ORDER BY run_timestamp DESC LIMIT 1
            ) rr ON true
            ORDER BY r.reservoir_id
            """
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]
