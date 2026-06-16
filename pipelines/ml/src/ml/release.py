"""Release-risk orchestrator (FR-ML-3): turn each reservoir's latest forecast trajectory
into a persisted `ReleaseRisk` row (ADR-0001). Append-only (audit trail, NFR-REL-5).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from ml.release_risk import assess_release_risk

_RR_INSERT = text(
    """
    INSERT INTO release_risk
      (reservoir_id, run_timestamp, release_probability, risk_level,
       estimated_lead_time_days, contributing_factors, model_version_id, input_abt_version)
    VALUES
      (:r, :ts, :prob, :level, :lead, CAST(:factors AS jsonb), :mv, :abt)
    """
)


def run_release_risk(
    session: Session, abt_version: str = "abt_v1", run_timestamp: datetime | None = None
) -> dict:
    """Assess + persist release-risk for every reservoir with a current forecast."""
    run_ts = run_timestamp or datetime.now(UTC)
    conn = session.connection()
    reservoirs = conn.execute(text("SELECT reservoir_id, release_thresholds FROM reservoir")).all()

    out: dict[str, dict] = {}
    for rid, thresholds in reservoirs:
        latest = conn.execute(
            text("SELECT max(run_timestamp) FROM prediction WHERE reservoir_id = :r"),
            {"r": rid},
        ).scalar()
        if latest is None:
            continue
        preds = conn.execute(
            text(
                "SELECT predicted_pct_filled, interval_high, model_version_id FROM prediction "
                "WHERE reservoir_id = :r AND run_timestamp = :t ORDER BY horizon_date"
            ),
            {"r": rid, "t": latest},
        ).all()
        pred_pct = [float(p[0]) for p in preds]
        interval_high = [float(p[1]) if p[1] is not None else float(p[0]) for p in preds]
        horizons = list(range(1, len(preds) + 1))
        mv_id = preds[0][2]

        gt = conn.execute(
            text(
                "SELECT pct_filled, normal_storage_pct FROM ground_truth "
                "WHERE reservoir_id = :r AND pct_filled IS NOT NULL ORDER BY date DESC LIMIT 1"
            ),
            {"r": rid},
        ).first()
        if gt is None:
            continue
        current_pct = float(gt[0])
        normal_pct = float(gt[1]) if gt[1] is not None else current_pct

        risk = assess_release_risk(
            horizons, pred_pct, interval_high, thresholds, normal_pct, current_pct
        )
        session.execute(
            _RR_INSERT,
            {
                "r": rid,
                "ts": run_ts,
                "prob": risk.release_probability,
                "level": risk.risk_level,
                "lead": risk.estimated_lead_time_days,
                "factors": json.dumps(risk.contributing_factors),
                "mv": mv_id,
                "abt": abt_version,
            },
        )
        out[rid] = {
            "risk_level": risk.risk_level,
            "release_probability": risk.release_probability,
            "estimated_lead_time_days": risk.estimated_lead_time_days,
        }
    return {"assessments": out, "count": len(out)}
