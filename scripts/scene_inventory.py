"""Stage-1.1 recon: Sentinel-1 scene inventory per reservoir (Replan.md §3, Stage 1.1).

For each reservoir in the registry, queries the live S1 GRD archive over the real
(JRC-GSW-derived) AOI and reports, per orbit/pass and per platform era:

- scene counts by year and platform (S1A / S1B / S1C availability picture),
- how many scenes *fully cover* the AOI (the production series constraint, B2),
- revisit cadence on the recommended orbit (median / p90 / max gap, by era),
- bulletin-match quality: for every historical bulletin date, the offset to the
  nearest full-coverage scene, split monsoon (Jun-Sep) vs non-monsoon.

These numbers size the whole Phase-1 backfill: match tolerance, seasonal coverage,
and how many of the ~580 bulletins get a usable training pair. Outputs:

- ``data/recon/scene_inventory_<slug>.csv``  (per-scene table)
- ``docs/recon/scene-inventory-<date>.md``   (the report)

Run: ``uv run python scripts/scene_inventory.py`` (needs geeservice.json / GEE_SA_KEY_FILE).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
from data_engineering.reservoirs import REGISTRY, ReservoirMeta
from remote_sensing.gee_real import GeeExtractionError, derive_aoi, init_ee

ROOT = Path(__file__).resolve().parents[1]
BULLETINS_CSV = ROOT / "data" / "historical" / "reservoir_timeseries.csv"
CSV_OUT_DIR = ROOT / "data" / "recon"
REPORT_DIR = ROOT / "docs" / "recon"

S1_START = "2014-10-01"
MONSOON_MONTHS = {6, 7, 8, 9}
# Platform eras for cadence reporting: S1B failed 2021-12-23; S1C operational 2025.
ERAS = [
    ("S1A+S1B", "2015-01-01", "2021-12-23"),
    ("S1A only", "2021-12-24", "2024-12-31"),
    ("S1A+S1C", "2025-01-01", "2099-01-01"),
]
OFFSET_BUCKETS = [1, 3, 5, 7]


def scene_table(meta: ReservoirMeta) -> tuple[pd.DataFrame, dict]:
    """Query the S1 GRD archive over the reservoir's real AOI; one row per scene."""
    import ee

    init_ee()
    aoi_geojson = derive_aoi(meta.dam_lon, meta.dam_lat)
    aoi = ee.Geometry(aoi_geojson)
    aoi_km2 = aoi.area(maxError=100).getInfo() / 1e6

    coll = (
        ee.ImageCollection("COPERNICUS/S1_GRD")
        .filterBounds(aoi)
        .filterDate(S1_START, date.today().isoformat())
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
    )

    def props(img: object) -> object:
        image = ee.Image(img)  # ee types are Any; rebind so attribute access typechecks
        return ee.Feature(
            None,
            {
                "t": image.get("system:time_start"),
                "platform": ee.String(image.get("system:index")).slice(0, 3),
                "orbit": image.get("relativeOrbitNumber_start"),
                "pass": image.get("orbitProperties_pass"),
                "covers": image.geometry().contains(aoi, maxError=100),
            },
        )

    feats = coll.map(props).getInfo()["features"]
    rows = [f["properties"] for f in feats]
    df = pd.DataFrame(rows)
    if df.empty:
        raise GeeExtractionError(f"no S1 IW/VH scenes intersect the {meta.slug} AOI")
    df["date"] = pd.to_datetime(df["t"], unit="ms").dt.date
    df["year"] = pd.to_datetime(df["t"], unit="ms").dt.year
    df = df.drop(columns="t").sort_values("date").reset_index(drop=True)
    return df, {"aoi_km2": aoi_km2}


def cadence(dates: pd.Series) -> dict[str, dict[str, float | int]]:
    """Gap statistics (days) between consecutive scenes, per platform era."""
    out: dict[str, dict[str, float | int]] = {}
    d = pd.to_datetime(pd.Series(sorted(dates.unique())))
    for label, lo, hi in ERAS:
        sel = d[(d >= lo) & (d <= hi)]
        if len(sel) < 2:
            out[label] = {"scenes": int(len(sel))}
            continue
        gaps = sel.diff().dt.days.dropna()
        out[label] = {
            "scenes": int(len(sel)),
            "median_gap_d": float(gaps.median()),
            "p90_gap_d": float(gaps.quantile(0.9)),
            "max_gap_d": int(gaps.max()),
        }
    return out


def bulletin_offsets(bulletin_dates: pd.Series, scene_dates: pd.Series) -> pd.DataFrame:
    """Offset (days) from each bulletin to its nearest scene, tagged by season."""
    scenes = pd.to_datetime(pd.Series(sorted(scene_dates.unique())))
    rows = []
    for b in pd.to_datetime(bulletin_dates):
        off = int((scenes - b).abs().min().days)
        rows.append(
            {"season": "monsoon" if b.month in MONSOON_MONTHS else "non-monsoon", "offset_d": off}
        )
    return pd.DataFrame(rows)


def offset_summary(off: pd.DataFrame) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for season, grp in off.groupby("season"):
        n = len(grp)
        out[str(season)] = {"bulletins": n} | {
            f"within_{k}d_pct": round(100 * (grp["offset_d"] <= k).sum() / n, 1)
            for k in OFFSET_BUCKETS
        }
    return out


def main() -> int:
    CSV_OUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    bulletins = pd.read_csv(BULLETINS_CSV, usecols=["RESERVOIR NAME", "DATE"])

    lines = [
        f"# Sentinel-1 scene inventory — {date.today().isoformat()}",
        "",
        "Stage-1.1 recon (Replan.md §3). Full coverage = scene footprint contains the",
        "entire JRC-GSW-derived AOI (the production-series requirement, B2).",
        "",
    ]

    for name, meta in REGISTRY.items():
        print(f"[{meta.slug}] deriving AOI + querying S1 archive ...", flush=True)
        df, info = scene_table(meta)
        df.to_csv(CSV_OUT_DIR / f"scene_inventory_{meta.slug}.csv", index=False)

        by_orbit = (
            df.groupby(["orbit", "pass"])
            .agg(
                scenes=("date", "count"),
                full_coverage=("covers", "sum"),
                first=("date", "min"),
                last=("date", "max"),
            )
            .sort_values("full_coverage", ascending=False)
        )
        best_orbit, best_pass = by_orbit.index[0]
        best = df[(df["orbit"] == best_orbit) & (df["pass"] == best_pass) & df["covers"]]
        year_platform = df.pivot_table(
            index="year", columns="platform", values="date", aggfunc="count", fill_value=0
        )

        b_dates = bulletins.loc[bulletins["RESERVOIR NAME"] == name, "DATE"]
        off_best = offset_summary(bulletin_offsets(b_dates, best["date"]))
        off_any = offset_summary(bulletin_offsets(b_dates, df.loc[df["covers"], "date"]))

        def fence(table: str) -> list[str]:
            # to_string() tables are plain text; fence them so markdown keeps alignment.
            return ["```text", table, "```", ""]

        lines += [
            f"## {meta.name} (`{meta.slug}`) — AOI {info['aoi_km2']:.0f} km²",
            "",
            f"Scenes intersecting AOI: **{len(df)}** · fully covering: "
            f"**{int(df['covers'].sum())}**",
            "",
            "### Scenes per orbit/pass",
            "",
            *fence(by_orbit.to_string()),
            f"**Recommended orbit: {best_orbit} {best_pass}** ({len(best)} full-coverage scenes)",
            "",
            "### Scenes per year × platform",
            "",
            *fence(year_platform.to_string()),
            "### Cadence on recommended orbit (full-coverage scenes)",
            "",
            *fence(pd.DataFrame(cadence(best["date"])).T.to_string()),
            "### Bulletin → nearest full-coverage scene offset",
            "",
            "Recommended orbit only:",
            "",
            *fence(pd.DataFrame(off_best).T.to_string()),
            "Any fully-covering orbit:",
            "",
            *fence(pd.DataFrame(off_any).T.to_string()),
        ]
        print(
            f"[{meta.slug}] {len(df)} scenes, best orbit {best_orbit} {best_pass} "
            f"({len(best)} full-coverage)",
            flush=True,
        )

    report = REPORT_DIR / f"scene-inventory-{date.today().isoformat()}.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"report: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
