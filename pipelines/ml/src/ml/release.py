"""Release-risk orchestrator (FR-ML-3): turn each reservoir's latest forecast trajectory
into a persisted `ReleaseRisk` row (ADR-0001). Append-only (audit trail, NFR-REL-5).
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime, timedelta

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
                "SELECT horizon_date, predicted_pct_filled, interval_low, interval_high, "
                "model_version_id FROM prediction "
                "WHERE reservoir_id = :r AND run_timestamp = :t ORDER BY horizon_date"
            ),
            {"r": rid, "t": latest},
        ).all()
        if not preds:
            continue
        base_date = min(p[0] for p in preds) - timedelta(days=1)
        gt = conn.execute(
            text(
                "SELECT date, pct_filled, normal_storage_pct FROM ground_truth "
                "WHERE reservoir_id = :r AND pct_filled IS NOT NULL AND date <= :base "
                "ORDER BY date DESC LIMIT 1"
            ),
            {"r": rid, "base": base_date},
        ).first()
        if gt is None:
            continue
        current_pct = float(gt[1])
        normal_pct = float(gt[2]) if gt[2] is not None else current_pct
        # Key horizons by the horizon_date column relative to the forecast base —
        # never by row order (C7); rows are not guaranteed contiguous or ordered.
        traj = sorted(
            (((p[0] - base_date).days, p) for p in preds if (p[0] - base_date).days >= 1),
            key=lambda hp: hp[0],
        )
        if not traj:
            continue
        horizons = [h for h, _ in traj]
        pred_pct = [float(p[1]) for _, p in traj]
        # NULL bounds stay None: assess_release_risk treats a missing interval as
        # missing uncertainty (widest-known / fallback), never as zero width (C7).
        interval_low = [float(p[2]) if p[2] is not None else None for _, p in traj]
        interval_high = [float(p[3]) if p[3] is not None else None for _, p in traj]
        # Rows could carry mixed model versions; take the modal one, deterministically,
        # rather than assuming row 0 speaks for the whole trajectory (C7).
        mv_id = Counter(p[4] for _, p in traj).most_common(1)[0][0]

        risk = assess_release_risk(
            horizons, pred_pct, interval_low, interval_high, thresholds, normal_pct, current_pct
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
