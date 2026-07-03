"""Bulletin bronze→silver ingest (FR-DE-1/2/6): CSV → clean → idempotent upsert into
``ground_truth``. Quarantine rows that cannot be keyed (no reservoir/date) are counted,
not inserted; in-band rows carry their ``row_quality`` label.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from data_engineering.cleaning import clean_bulletins
from data_engineering.validation import validate_bulletins

_UPSERT = text(
    """
    INSERT INTO ground_truth
      (reservoir_id, date, level_m, live_storage_bcm, pct_filled, frl_m,
       live_capacity_bcm, normal_storage_pct, benefits_irr_cca, benefits_hydel_mw,
       source_pdf, row_quality)
    VALUES
      (:reservoir_id, :date, :level_m, :live_storage_bcm, :pct_filled, :frl_m,
       :live_capacity_bcm, :normal_storage_pct, :benefits_irr_cca, :benefits_hydel_mw,
       :source_pdf, :row_quality)
    ON CONFLICT (reservoir_id, date) DO UPDATE SET
       level_m = EXCLUDED.level_m, live_storage_bcm = EXCLUDED.live_storage_bcm,
       pct_filled = EXCLUDED.pct_filled, frl_m = EXCLUDED.frl_m,
       live_capacity_bcm = EXCLUDED.live_capacity_bcm,
       normal_storage_pct = EXCLUDED.normal_storage_pct,
       benefits_irr_cca = EXCLUDED.benefits_irr_cca,
       benefits_hydel_mw = EXCLUDED.benefits_hydel_mw,
       source_pdf = EXCLUDED.source_pdf, row_quality = EXCLUDED.row_quality
    """
)

_COLS = [
    "reservoir_id",
    "date",
    "level_m",
    "live_storage_bcm",
    "pct_filled",
    "frl_m",
    "live_capacity_bcm",
    "normal_storage_pct",
    "benefits_irr_cca",
    "benefits_hydel_mw",
    "source_pdf",
    "row_quality",
]


def _na_to_none(v):
    try:
        return None if pd.isna(v) else v
    except (TypeError, ValueError):
        return v


def _records(df: pd.DataFrame) -> list[dict]:
    records = []
    for _, r in df.iterrows():
        rec = {c: _na_to_none(r.get(c)) for c in _COLS}
        if rec["date"] is not None and not isinstance(rec["date"], str):
            rec["date"] = pd.Timestamp(rec["date"]).date()
        records.append(rec)
    return records


def ingest_bulletins(session: Session, csv_path: str | Path) -> dict:
    """Load + clean + upsert bulletins. Returns row counts (loaded/inserted/quarantined)."""
    raw = pd.read_csv(csv_path)
    cleaned = clean_bulletins(raw)
    # Silver-boundary validation (AC-12): fail loudly if any 'ok' row violates the
    # bulletin schema — flagged (low_confidence/quarantine) rows are carried, not gated.
    validate_bulletins(cleaned)
    keyable = cleaned[cleaned["reservoir_id"].notna() & cleaned["date"].notna()]
    dropped = len(cleaned) - len(keyable)
    records = _records(keyable)
    if records:
        session.execute(_UPSERT, records)
    n_quarantine = int((keyable["row_quality"] == "quarantine").sum())
    return {
        "loaded": len(raw),
        "cleaned": len(cleaned),
        "upserted": len(records),
        "unkeyable_dropped": dropped,
        "quarantine_flagged": n_quarantine,
    }
