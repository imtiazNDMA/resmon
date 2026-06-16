"""Bulletin cleaning library (FR-DE-2), promoted from ``build_unified_dataset.py``.

Pure transforms over a bulletin DataFrame: canonical names, IST date parsing, and the
quality gates that route bad rows to quarantine rather than dropping silently (plan R-2).
"""

from __future__ import annotations

import re

import pandas as pd

from data_engineering.reservoirs import REGISTRY, meta_for_name

# Year-leading ISO dates are unambiguous and must NOT be parsed dayfirst.
_ISO_DATE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}")


def canonical_name(raw: object) -> str | None:
    """Map a raw dam name (any alias) to its canonical bulletin name."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    text = str(raw).strip().lower()
    aliases = {
        "gobind": "GOBIND SAGAR",
        "bhakra": "GOBIND SAGAR",
        "pong": "PONG DAM",
        "thein": "THEIN DAM",
        "ranjit sagar": "THEIN DAM",
    }
    for alias, name in aliases.items():
        if alias in text:
            return name
    return None


def parse_ist_date(value: object) -> pd.Timestamp:
    """Parse the bulletin date encodings; the result is an IST calendar date."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return pd.NaT
    if isinstance(value, pd.Timestamp):
        return value
    text = str(value).strip()
    if _ISO_DATE.match(text):
        return pd.to_datetime(text, errors="coerce")
    return pd.to_datetime(text, dayfirst=True, errors="coerce")


def quality_label(row: pd.Series) -> str:
    """Classify a cleaned bulletin row (FR-DE-4). Physically-impossible → quarantine;
    out-of-band fill → low_confidence; otherwise ok."""
    pct = row.get("pct_filled")
    level = row.get("level_m")
    if (pd.notna(pct) and pct < 0) or (pd.notna(level) and level < 0):
        return "quarantine"
    if pd.notna(pct) and (pct > 110):
        return "low_confidence"
    return "ok"


def clean_bulletins(raw: pd.DataFrame) -> pd.DataFrame:
    """Standardise the unified bulletin CSV (§6.2 columns) into the silver frame keyed
    by ``(reservoir_id, date)`` with a ``row_quality`` label. Unmatched names / dates
    are marked ``quarantine`` (kept, never silently dropped)."""
    df = pd.DataFrame(
        {
            "bulletin_name": raw["RESERVOIR NAME"].map(canonical_name),
            "date": raw["DATE"].map(parse_ist_date),
            "level_m": pd.to_numeric(raw["CURRENT RESERVOIR LEVEL (M)"], errors="coerce"),
            "live_storage_bcm": pd.to_numeric(raw["CURRENT LIVE STORAGE (BCM)"], errors="coerce"),
            "pct_filled": pd.to_numeric(raw["pct_filled"], errors="coerce"),
            "normal_storage_pct": pd.to_numeric(
                raw["STORAGE AS % OF LIVE CAPACITY AT FRL - NORMAL STORAGE"], errors="coerce"
            ),
            "benefits_irr_cca": pd.to_numeric(raw["BENEFITS - IRR-CCA"], errors="coerce"),
            "benefits_hydel_mw": pd.to_numeric(raw["BENEFITS - HYDEL IN MW"], errors="coerce"),
            "source_pdf": raw["SOURCE_PDF"],
        }
    )
    df["reservoir_id"] = df["bulletin_name"].map(
        lambda n: REGISTRY[n].slug if isinstance(n, str) and n in REGISTRY else None
    )
    df["frl_m"] = df["bulletin_name"].map(lambda n: m.frl_m if (m := meta_for_name(n)) else None)
    df["live_capacity_bcm"] = df["bulletin_name"].map(
        lambda n: m.live_capacity_bcm if (m := meta_for_name(n)) else None
    )
    df["row_quality"] = df.apply(quality_label, axis=1)
    # Unresolvable identity/date → quarantine (kept, flagged).
    bad = df["reservoir_id"].isna() | df["date"].isna()
    df.loc[bad, "row_quality"] = "quarantine"
    # Deduplicate by (reservoir_id, ISO week), keeping the latest in-week observation.
    df = df.sort_values("date")
    iso = df["date"].dt.isocalendar()
    df = df.assign(_y=iso["year"], _w=iso["week"]).drop_duplicates(
        subset=["reservoir_id", "_y", "_w"], keep="last"
    )
    return df.drop(columns=["_y", "_w"])
