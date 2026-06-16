"""Read repositories — SQL queries behind the API (FR-API-1/2). Read-only; the serving
layer never writes (NFR-SEC-3). All return plain dicts/rows for the routers to shape.
"""

from __future__ import annotations

from datetime import date

from core.config import get_settings
from sqlalchemy import text
from sqlalchemy.orm import Session


def _f(v: object) -> float | None:
    """Postgres ``numeric`` arrives as ``Decimal`` (→ JSON string); coerce to a JSON number."""
    return float(v) if v is not None else None  # type: ignore[arg-type]


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
    return [
        {**dict(r), "frl_m": _f(r["frl_m"]), "live_capacity_bcm": _f(r["live_capacity_bcm"])}
        for r in rows
    ]


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
    if not row:
        return None
    return {
        **dict(row),
        "frl_m": _f(row["frl_m"]),
        "live_capacity_bcm": _f(row["live_capacity_bcm"]),
    }


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
            "SELECT max(acquisition_date) FROM observation WHERE reservoir_id = :r "
            "AND extraction_method <> 'stub'"
        ),
        {"r": rid},
    ).scalar()
    # Graceful-degradation / staleness (NFR-REL-6, D8): age from the freshest signal
    # (SAR acquisition if any, else the latest bulletin).
    threshold = get_settings().data_staleness_threshold_days
    ref = last_acq or gt["date"]
    age_days = (date.today() - ref).days if ref is not None else None
    return {
        "reservoir_id": rid,
        "as_of": gt["date"],
        "pct_filled": float(gt["pct_filled"]),
        "level_m": float(gt["level_m"]) if gt["level_m"] is not None else None,
        "live_storage_bcm": float(gt["live_storage_bcm"])
        if gt["live_storage_bcm"] is not None
        else None,
        "risk_level": risk["risk_level"] if risk else None,
        "release_probability": float(risk["release_probability"]) if risk else None,
        "estimated_lead_time_days": float(risk["estimated_lead_time_days"])
        if risk and risk["estimated_lead_time_days"] is not None
        else None,
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
    return [
        {
            "date": r["date"],
            "pct_filled": _f(r["pct_filled"]),
            "level_m": _f(r["level_m"]),
            "live_storage_bcm": _f(r["live_storage_bcm"]),
            "normal_storage_pct": _f(r["normal_storage_pct"]),
        }
        for r in reversed(rows)
    ]


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


def reservoir_features(s: Session) -> list[dict]:
    rows = (
        s.execute(
            text(
                """
            SELECT r.reservoir_id, r.name, r.frl_m,
                   ST_AsGeoJSON(r.dam_point) AS dam_point_geojson,
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
