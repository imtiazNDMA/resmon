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
    gt = (
        s.execute(
            text(
                "SELECT date, pct_filled, level_m, live_storage_bcm FROM ground_truth "
                "WHERE reservoir_id = :r AND pct_filled IS NOT NULL ORDER BY date DESC LIMIT 1"
            ),
            {"r": rid},
        )
        .mappings()
        .first()
    )
    if gt is None:
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
    ref = last_acq or gt["date"]
    age_days = (datetime.now(_IST).date() - ref).days if ref is not None else None
    # Unknown age is still a well-formed payload: stale=true, age null (D9).
    return {
        "reservoir_id": rid,
        "as_of": gt["date"],
        "pct_filled": gt["pct_filled"],
        "level_m": gt["level_m"],
        "live_storage_bcm": gt["live_storage_bcm"],
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
                "SELECT acquisition_date::text AS date, surface_area, area_confidence "
                "FROM observation "
                f"WHERE reservoir_id = :r AND {_REAL_OBS} "
                "ORDER BY acquisition_date"
            ),
            {"r": rid},
        )
        .mappings()
        .all()
    )
    return [
        {"date": r["date"], "area_km2": r["surface_area"], "confidence": r["area_confidence"]}
        for r in rows
    ]


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
