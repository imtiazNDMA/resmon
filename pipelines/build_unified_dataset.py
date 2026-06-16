"""Build the unified weekly reservoir ground-truth dataset.

Cleans and merges the raw files in ``data/to_be_cleaned/`` with the already-clean
2025 historical file into a single weekly time series conforming exactly to the
ground-truth schema (requirements.md §6.2).

Design spec: docs/superpowers/specs/2026-06-16-unified-reservoir-dataset-design.md

Run:  uv run python pipelines/build_unified_dataset.py
      (or)  python pipelines/build_unified_dataset.py
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

# Year-leading ISO dates (e.g. "2025-05-08") are unambiguous and must NOT be
# parsed with dayfirst=True (pandas would read them as YYYY-DD-MM and flip
# month/day). Everything else here is European d/m/y or d.m.y and needs dayfirst.
_ISO_DATE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}")

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "to_be_cleaned"
HISTORICAL = ROOT / "data" / "historical" / "reservoir_timeseries.csv"
OUT_DIR = ROOT / "data" / "db"
OUT_FILE = OUT_DIR / "reservoir_unified_weekly.csv"

# --------------------------------------------------------------------------- #
# Conversions — empirically validated against the 2025 historical file
#   1680 ft * 0.3048      = 512.06 m   vs historical FRL 512.00  ✓
#   5.05 MAF * 1.23348... = 6.229 BCM  vs historical capacity 6.229 ✓
# --------------------------------------------------------------------------- #
FT_TO_M = 0.3048
MAF_TO_BCM = 1.233481838

# --------------------------------------------------------------------------- #
# Canonical reservoir registry: alias -> identity + static metadata.
# Static fields (FRL, capacity, benefits) are backfilled into every row from
# the canonical 2025 values, overriding any bad per-source value.
# --------------------------------------------------------------------------- #
REGISTRY = {
    "GOBIND SAGAR": {
        "aliases": ("gobind", "bhakra"),
        "frl_m": 512.00,
        "capacity_bcm": 6.229,
        "irr_cca": 676.000,
        "hydel_mw": 1379.000,
    },
    "PONG DAM": {
        "aliases": ("pong",),
        "frl_m": 423.67,
        "capacity_bcm": 6.157,
        "irr_cca": 0.000,
        "hydel_mw": 396.000,
    },
    "THEIN DAM": {
        "aliases": ("thein", "ranjit sagar"),
        "frl_m": 527.91,
        "capacity_bcm": 2.344,
        "irr_cca": 348.000,
        "hydel_mw": 600.000,
    },
}

# Source precedence when the same (reservoir, ISO week) appears in several
# sources. Lower rank wins.
SOURCE_RANK = {
    "historical_2025": 0,
    "cwc_weekly": 1,
    "daily_sitrep": 2,
    "csv_2024": 3,
}

# Final output column order (requirements.md §6.2).
OUTPUT_COLUMNS = [
    "SR. NO.",
    "RESERVOIR NAME",
    "FRL (M)",
    "CURRENT RESERVOIR LEVEL (M)",
    "LIVE CAPACITY AT FRL (BCM)",
    "CURRENT LIVE STORAGE (BCM)",
    "DATE",
    "STORAGE AS % OF LIVE CAPACITY AT FRL - CURRENT YEAR",
    "STORAGE AS % OF LIVE CAPACITY AT FRL - LAST YEAR",
    "STORAGE AS % OF LIVE CAPACITY AT FRL - NORMAL STORAGE",
    "BENEFITS - IRR-CCA",
    "BENEFITS - HYDEL IN MW",
    "SOURCE_PDF",
    "pct_filled",
]

# Columns of the normalized intermediate frame produced by every reader.
INTERMEDIATE = [
    "reservoir",
    "date",
    "level_m",
    "storage_bcm",
    "last_year_pct",
    "normal_pct",
    "current_year_pct",
    "source_tag",
    "source_pdf",
]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def canonical_name(raw: object) -> str | None:
    """Map a raw dam name (any alias / descriptive form) to its canonical name."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    text = str(raw).strip().lower()
    for name, meta in REGISTRY.items():
        if any(alias in text for alias in meta["aliases"]):
            return name
    return None


def parse_date(value: object) -> pd.Timestamp | pd.NaT:
    """Parse the many date encodings in the sources (datetime, ISO, d/m/y, d.m.y)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return pd.NaT
    if isinstance(value, pd.Timestamp):
        return value
    text = str(value).strip()
    # ISO (year-first) must parse without dayfirst; d/m/y and d.m.y need dayfirst.
    if _ISO_DATE.match(text):
        return pd.to_datetime(text, errors="coerce")
    return pd.to_datetime(text, dayfirst=True, errors="coerce")


def empty_intermediate() -> dict:
    return {c: pd.NA for c in INTERMEDIATE}


# --------------------------------------------------------------------------- #
# Source readers -> normalized intermediate frame
# --------------------------------------------------------------------------- #
def read_historical_2025() -> pd.DataFrame:
    """Already in schema/units; map straight across, keep its real %s."""
    df = pd.read_csv(HISTORICAL)
    out = pd.DataFrame(
        {
            "reservoir": df["RESERVOIR NAME"].map(canonical_name),
            "date": df["DATE"].map(parse_date),
            "level_m": pd.to_numeric(df["CURRENT RESERVOIR LEVEL (M)"], errors="coerce"),
            "storage_bcm": pd.to_numeric(df["CURRENT LIVE STORAGE (BCM)"], errors="coerce"),
            "last_year_pct": pd.to_numeric(
                df["STORAGE AS % OF LIVE CAPACITY AT FRL - LAST YEAR"], errors="coerce"
            ),
            "normal_pct": pd.to_numeric(
                df["STORAGE AS % OF LIVE CAPACITY AT FRL - NORMAL STORAGE"], errors="coerce"
            ),
            "current_year_pct": pd.NA,  # recomputed uniformly later
            "source_tag": "historical_2025",
            "source_pdf": df["SOURCE_PDF"],
        }
    )
    return out[INTERMEDIATE]


def read_csv_2024() -> pd.DataFrame:
    """2024 weekly spreadsheet: ft/MAF; sparse 'Dated' needs forward-fill."""
    path = RAW_DIR / "Indian Dams Storage Level(2).xlsx - Sheet1.csv"
    df = pd.read_csv(path)
    df["Dated"] = df["Dated"].ffill()  # measurement date filled only on first dam/week
    out = pd.DataFrame(
        {
            "reservoir": df["Name of Dam"].map(canonical_name),
            "date": df["Dated"].map(parse_date),
            "level_m": pd.to_numeric(df["Current Reservoir Level (feet)"], errors="coerce")
            * FT_TO_M,
            "storage_bcm": pd.to_numeric(df["Current Live Storage (MAF)"], errors="coerce")
            * MAF_TO_BCM,
            "last_year_pct": pd.to_numeric(df["Storage Last Year %"], errors="coerce"),
            "normal_pct": pd.NA,
            "current_year_pct": pd.NA,
            "source_tag": "csv_2024",
            "source_pdf": path.name,
        }
    )
    return out[INTERMEDIATE]


def read_daily_sitrep() -> pd.DataFrame:
    """Daily SITREP (MAIN sheet, all 3 dams): ft/MAF, daily cadence."""
    path = RAW_DIR / "Indian_Dams_Data-2020_2024.xlsx"
    df = pd.read_excel(path, sheet_name="MAIN")
    out = pd.DataFrame(
        {
            "reservoir": df["Name of Dam"].map(canonical_name),
            "date": df["Date of SITREP"].map(parse_date),
            "level_m": pd.to_numeric(df["Current Level"], errors="coerce") * FT_TO_M,
            "storage_bcm": pd.to_numeric(df["Current Live Storage (MAF)"], errors="coerce")
            * MAF_TO_BCM,
            "last_year_pct": pd.NA,
            "normal_pct": pd.NA,
            "current_year_pct": pd.NA,
            "source_tag": "daily_sitrep",
            "source_pdf": path.name,
        }
    )
    return out[INTERMEDIATE]


def read_cwc_weekly() -> pd.DataFrame:
    """CWC 'Eastern Rivers' weekly bulletin: one sheet per dam, ft/MAF.

    Bhakra header is on row 0; Pong/Thein have 4 title rows then a header.
    Columns are positional and identical across sheets once the header is found.
    """
    path = RAW_DIR / "Weekly Level and Capacity of Eastern Rivers from (cwc.gov.in) (2015-2024).xlsx"
    frames = []
    for sheet in ("Bhakra", "Pong", "Thein"):
        raw = pd.read_excel(path, sheet_name=sheet, header=None)
        # Find the header row: the one whose first cell == "Date".
        header_idx = next(
            i for i in range(len(raw)) if str(raw.iloc[i, 0]).strip().lower() == "date"
        )
        body = raw.iloc[header_idx + 1 :]
        # Positional columns: 0=Date, 1=level(ft), 2=cap(MAF), 3=storage(MAF),
        #                     4=storage%, 5=storage last year%.
        frames.append(
            pd.DataFrame(
                {
                    "reservoir": canonical_name(sheet),
                    "date": body.iloc[:, 0].map(parse_date),
                    "level_m": pd.to_numeric(body.iloc[:, 1], errors="coerce") * FT_TO_M,
                    "storage_bcm": pd.to_numeric(body.iloc[:, 3], errors="coerce") * MAF_TO_BCM,
                    "last_year_pct": pd.to_numeric(body.iloc[:, 5], errors="coerce"),
                    "normal_pct": pd.NA,
                    "current_year_pct": pd.NA,
                    "source_tag": "cwc_weekly",
                    "source_pdf": path.name,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)[INTERMEDIATE]


# --------------------------------------------------------------------------- #
# Transform stages
# --------------------------------------------------------------------------- #
def quarantine(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows that fail basic quality gates; log what and why."""
    n0 = len(df)

    bad_name = df["reservoir"].isna()
    bad_date = df["date"].isna()
    bad_values = df["level_m"].isna() & df["storage_bcm"].isna()
    drop = bad_name | bad_date | bad_values
    if drop.any():
        print(
            f"  quarantined {int(drop.sum())} rows "
            f"(no reservoir match: {int(bad_name.sum())}, "
            f"unparseable date: {int(bad_date.sum())}, "
            f"no level & no storage: {int(bad_values.sum())})"
        )
    df = df[~drop].copy()

    # Reject physically impossible negatives.
    neg = (df["level_m"] < 0) | (df["storage_bcm"] < 0)
    if neg.any():
        print(f"  quarantined {int(neg.sum())} rows with negative level/storage")
        df = df[~neg].copy()

    print(f"  rows: {n0} -> {len(df)}")
    return df


def collapse_to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Resample to one row per (source, reservoir, ISO week), keeping the latest
    observation in each week. Applies to all sources but only changes the daily one."""
    iso = df["date"].dt.isocalendar()
    df = df.assign(iso_year=iso["year"], iso_week=iso["week"])
    df = df.sort_values("date")
    df = df.drop_duplicates(
        subset=["source_tag", "reservoir", "iso_year", "iso_week"], keep="last"
    )
    return df


def dedup_across_sources(df: pd.DataFrame) -> pd.DataFrame:
    """Keep one row per (reservoir, ISO week) using source precedence."""
    df = df.assign(rank=df["source_tag"].map(SOURCE_RANK))
    df = df.sort_values(["reservoir", "iso_year", "iso_week", "rank"])
    before = len(df)
    df = df.drop_duplicates(subset=["reservoir", "iso_year", "iso_week"], keep="first")
    print(f"  cross-source dedup: {before} -> {len(df)} rows")
    return df


def backfill_and_compute(df: pd.DataFrame) -> pd.DataFrame:
    """Backfill static registry fields and compute derived percentages."""
    df = df.copy()
    df["FRL (M)"] = df["reservoir"].map(lambda r: REGISTRY[r]["frl_m"])
    df["LIVE CAPACITY AT FRL (BCM)"] = df["reservoir"].map(lambda r: REGISTRY[r]["capacity_bcm"])
    df["BENEFITS - IRR-CCA"] = df["reservoir"].map(lambda r: REGISTRY[r]["irr_cca"])
    df["BENEFITS - HYDEL IN MW"] = df["reservoir"].map(lambda r: REGISTRY[r]["hydel_mw"])

    # pct_filled is the canonical derived fill; CURRENT YEAR % is its rounded form.
    df["pct_filled"] = df["storage_bcm"] / df["LIVE CAPACITY AT FRL (BCM)"] * 100
    df["current_year_pct"] = df["pct_filled"].round(2)

    # Flag (don't drop) fills outside the plausible 0–110% band.
    out_of_band = (df["pct_filled"] < 0) | (df["pct_filled"] > 110)
    if out_of_band.any():
        print(f"  WARNING: {int(out_of_band.sum())} rows have pct_filled outside 0–110%")
    return df


def assemble(df: pd.DataFrame) -> pd.DataFrame:
    """Project to the exact §6.2 schema, regenerate SR. NO., sort, format."""
    df = df.sort_values(["date", "reservoir"]).copy()
    df["DATE"] = df["date"].dt.strftime("%Y-%m-%d")
    # SR. NO. restarts at 1 within each date group.
    df["SR. NO."] = df.groupby("DATE").cumcount() + 1

    out = pd.DataFrame(
        {
            "SR. NO.": df["SR. NO."],
            "RESERVOIR NAME": df["reservoir"],
            "FRL (M)": df["FRL (M)"],
            "CURRENT RESERVOIR LEVEL (M)": df["level_m"].round(3),
            "LIVE CAPACITY AT FRL (BCM)": df["LIVE CAPACITY AT FRL (BCM)"],
            "CURRENT LIVE STORAGE (BCM)": df["storage_bcm"].round(3),
            "DATE": df["DATE"],
            "STORAGE AS % OF LIVE CAPACITY AT FRL - CURRENT YEAR": df["current_year_pct"],
            "STORAGE AS % OF LIVE CAPACITY AT FRL - LAST YEAR": df["last_year_pct"],
            "STORAGE AS % OF LIVE CAPACITY AT FRL - NORMAL STORAGE": df["normal_pct"],
            "BENEFITS - IRR-CCA": df["BENEFITS - IRR-CCA"],
            "BENEFITS - HYDEL IN MW": df["BENEFITS - HYDEL IN MW"],
            "SOURCE_PDF": df["source_pdf"],
            "pct_filled": df["pct_filled"],
        }
    )
    return out[OUTPUT_COLUMNS]


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def main() -> None:
    print("Reading sources...")
    readers = {
        "historical_2025": read_historical_2025,
        "cwc_weekly": read_cwc_weekly,
        "daily_sitrep": read_daily_sitrep,
        "csv_2024": read_csv_2024,
    }
    parts = []
    for tag, reader in readers.items():
        part = reader()
        print(f"  {tag}: {len(part)} raw rows")
        parts.append(part)

    df = pd.concat(parts, ignore_index=True)

    print("Quality gates...")
    df = quarantine(df)

    print("Resample daily -> weekly + dedup within source...")
    df = collapse_to_weekly(df)

    print("Dedup across sources (precedence: " + " > ".join(SOURCE_RANK) + ")...")
    df = dedup_across_sources(df)

    print("Backfill static fields + compute percentages...")
    df = backfill_and_compute(df)

    out = assemble(df)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_FILE, index=False)
    print(f"\nWrote {len(out)} rows -> {OUT_FILE.relative_to(ROOT)}")

    # Coverage summary.
    span = pd.to_datetime(out["DATE"])
    print(f"Span: {span.min().date()} -> {span.max().date()}")
    print("Rows per reservoir:")
    print(out["RESERVOIR NAME"].value_counts().to_string())


if __name__ == "__main__":
    main()
