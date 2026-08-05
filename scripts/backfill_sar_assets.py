"""Download local Sentinel-1 GeoTIFF assets from Earth Engine and register them.

This is the Phase-4 backfill path for local, zoomable SAR serving. It downloads VV,
VH, and optionally a simple VH-threshold water mask for one known Sentinel-1 scene,
then upserts the local asset catalog.

Run:
  uv run python scripts/backfill_sar_assets.py --reservoir pong --date 2020-01-05 \
    --scene-id S1A_TEST --aoi data/backfill/aoi_pong.geojson
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from core.config import get_settings
from remote_sensing.gee_real import S1_GRD, init_ee

from scripts.register_sar_assets import register_asset

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_ROOT = ROOT / "data" / "sar_cog"

Downloader = Callable[[str], bytes]
UrlFactory = Callable[[str, str, dict, int, float], str]


@dataclass(frozen=True)
class BackfillResult:
    reservoir_id: str
    acquisition_date: str
    scene_id: str
    vv_path: Path
    vh_path: Path
    water_mask_path: Path | None
    registered: bool
    skipped: bool = False


@dataclass(frozen=True)
class SceneSpec:
    scene_id: str
    acquisition_date: str


def backfill_scene_assets(
    *,
    reservoir_id: str,
    acquisition_date: str,
    scene_id: str,
    aoi_geojson: dict,
    out_root: Path = DEFAULT_OUT_ROOT,
    catalog_path: Path | None = None,
    include_water_mask: bool = True,
    water_mask_threshold_db: float = -18.0,
    scale_m: int = 10,
    dry_run: bool = False,
    downloader: Downloader | None = None,
    url_factory: UrlFactory | None = None,
) -> BackfillResult:
    """Download one scene's local rasters and register them in the SAR catalog."""
    scene_dir = out_root / reservoir_id / acquisition_date
    vv_path = scene_dir / "vv.tif"
    vh_path = scene_dir / "vh.tif"
    water_mask_path = scene_dir / "water_mask.tif" if include_water_mask else None
    if _outputs_exist(vv_path, vh_path, water_mask_path):
        return BackfillResult(
            reservoir_id, acquisition_date, scene_id, vv_path, vh_path, water_mask_path, False, True
        )
    if dry_run:
        return BackfillResult(
            reservoir_id, acquisition_date, scene_id, vv_path, vh_path, water_mask_path, False
        )

    scene_dir.mkdir(parents=True, exist_ok=True)
    make_url = url_factory or gee_download_url
    fetch = downloader or download_url

    _download_geotiff(
        make_url(scene_id, "VV", aoi_geojson, scale_m, water_mask_threshold_db), vv_path, fetch
    )
    _download_geotiff(
        make_url(scene_id, "VH", aoi_geojson, scale_m, water_mask_threshold_db), vh_path, fetch
    )
    if water_mask_path is not None:
        _download_geotiff(
            make_url(scene_id, "water_mask", aoi_geojson, scale_m, water_mask_threshold_db),
            water_mask_path,
            fetch,
        )

    register_asset(
        reservoir_id=reservoir_id,
        acquisition_date=acquisition_date,
        scene_id=scene_id,
        vv_path=vv_path,
        vh_path=vh_path,
        water_mask_path=water_mask_path,
        catalog_path=catalog_path,
    )
    return BackfillResult(
        reservoir_id, acquisition_date, scene_id, vv_path, vh_path, water_mask_path, True
    )


def backfill_scene_batch(
    *,
    reservoir_id: str,
    scenes: list[SceneSpec],
    aoi_geojson: dict,
    out_root: Path = DEFAULT_OUT_ROOT,
    catalog_path: Path | None = None,
    include_water_mask: bool = True,
    water_mask_threshold_db: float = -18.0,
    scale_m: int = 10,
    dry_run: bool = False,
    downloader: Downloader | None = None,
    url_factory: UrlFactory | None = None,
) -> list[BackfillResult]:
    """Backfill a sequence of discovered SAR scenes."""
    return [
        backfill_scene_assets(
            reservoir_id=reservoir_id,
            acquisition_date=scene.acquisition_date,
            scene_id=scene.scene_id,
            aoi_geojson=aoi_geojson,
            out_root=out_root,
            catalog_path=catalog_path,
            include_water_mask=include_water_mask,
            water_mask_threshold_db=water_mask_threshold_db,
            scale_m=scale_m,
            dry_run=dry_run,
            downloader=downloader,
            url_factory=url_factory,
        )
        for scene in scenes
    ]


def discover_scene_specs(
    *,
    aoi_geojson: dict,
    orbit_relative: int,
    pass_direction: str,
    start_date: str,
    end_date: str,
) -> list[SceneSpec]:
    """Discover full-coverage Sentinel-1 scenes for a date range."""
    import ee

    init_ee()
    aoi = ee.Geometry(aoi_geojson)
    gee_pass = {"ASC": "ASCENDING", "DESC": "DESCENDING"}.get(
        pass_direction.upper(), pass_direction.upper()
    )
    coll = (
        ee.ImageCollection(S1_GRD)
        .filterBounds(aoi)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
        .filter(ee.Filter.eq("relativeOrbitNumber_start", int(orbit_relative)))
        .filter(ee.Filter.eq("orbitProperties_pass", gee_pass))
        .filter(ee.Filter.contains(leftField=".geo", rightValue=aoi))
        .sort("system:time_start")
    )

    def props(img: object) -> object:
        image = ee.Image(img)
        return ee.Feature(
            None,
            {
                "scene_id": image.get("system:index"),
                "date": ee.Date(image.get("system:time_start")).format("YYYY-MM-dd"),
            },
        )

    features = (coll.map(props).getInfo() or {}).get("features", [])
    return [
        SceneSpec(str(f["properties"]["scene_id"]), str(f["properties"]["date"]))
        for f in features
    ]


def gee_download_url(
    scene_id: str,
    band: str,
    aoi_geojson: dict,
    scale_m: int,
    water_mask_threshold_db: float,
) -> str:
    """Create a short-lived Earth Engine GeoTIFF download URL for one scene/band."""
    import ee

    init_ee()
    aoi = ee.Geometry(aoi_geojson)
    image = ee.Image(f"{S1_GRD}/{scene_id}")
    if band == "water_mask":
        export = image.select("VH").lt(float(water_mask_threshold_db)).rename("water_mask")
    elif band in {"VV", "VH"}:
        export = image.select(band)
    else:
        raise ValueError(f"unsupported export band {band!r}")
    return str(
        export.clip(aoi).getDownloadURL(
            {
                "name": f"{scene_id}_{band.lower()}",
                "region": aoi,
                "scale": int(scale_m),
                "format": "GEO_TIFF",
            }
        )
    )


def download_url(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def _outputs_exist(vv_path: Path, vh_path: Path, water_mask_path: Path | None) -> bool:
    required = [vv_path, vh_path]
    if water_mask_path is not None:
        required.append(water_mask_path)
    return all(path.exists() for path in required)


def _download_geotiff(url: str, destination: Path, downloader: Downloader) -> None:
    payload = downloader(url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tmp_dir = Path(td)
        if zipfile.is_zipfile(_bytes_path(tmp_dir, payload)):
            _extract_first_tif(payload, destination, tmp_dir)
        else:
            tmp = destination.with_suffix(".tmp")
            tmp.write_bytes(payload)
            tmp.replace(destination)


def _bytes_path(tmp_dir: Path, payload: bytes) -> Path:
    path = tmp_dir / "download.bin"
    path.write_bytes(payload)
    return path


def _extract_first_tif(payload: bytes, destination: Path, tmp_dir: Path) -> None:
    archive = _bytes_path(tmp_dir, payload)
    with zipfile.ZipFile(archive) as zf:
        tif_names = [name for name in zf.namelist() if name.lower().endswith((".tif", ".tiff"))]
        if not tif_names:
            raise ValueError("Earth Engine download archive contained no GeoTIFF")
        tmp = destination.with_suffix(".tmp")
        tmp.write_bytes(zf.read(tif_names[0]))
        tmp.replace(destination)


def load_aoi(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def default_out_root() -> Path:
    """COG storage root from SAR_COG_ROOT, resolving relative paths from repo root."""
    root = Path(get_settings().sar_cog_root)
    return root if root.is_absolute() else ROOT / root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reservoir", required=True, help="reservoir id/slug")
    parser.add_argument("--date", help="single-scene SAR acquisition date, YYYY-MM-DD")
    parser.add_argument("--scene-id", help="single Sentinel-1 scene id")
    parser.add_argument("--start-date", help="batch discovery start date, YYYY-MM-DD")
    parser.add_argument("--end-date", help="batch discovery end date, YYYY-MM-DD")
    parser.add_argument("--orbit-relative", type=int, help="batch discovery relative orbit")
    parser.add_argument("--pass-direction", choices=("ASC", "DESC"), help="batch discovery pass")
    parser.add_argument("--aoi", type=Path, required=True, help="AOI GeoJSON path")
    parser.add_argument(
        "--out-root",
        type=Path,
        default=None,
        help="override SAR_COG_ROOT for local GeoTIFF/COG output",
    )
    parser.add_argument("--catalog", type=Path, default=None, help="override catalog SQLite path")
    parser.add_argument("--scale-m", type=int, default=10)
    parser.add_argument("--water-mask-threshold-db", type=float, default=-18.0)
    parser.add_argument("--no-water-mask", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="show target paths without download")
    args = parser.parse_args(argv)

    try:
        aoi_geojson = load_aoi(args.aoi)
        out_root = args.out_root or default_out_root()
        if args.scene_id or args.date:
            if not args.scene_id or not args.date:
                raise ValueError("single-scene mode requires both --scene-id and --date")
            results = [
                backfill_scene_assets(
                    reservoir_id=args.reservoir,
                    acquisition_date=args.date,
                    scene_id=args.scene_id,
                    aoi_geojson=aoi_geojson,
                    out_root=out_root,
                    catalog_path=args.catalog,
                    include_water_mask=not args.no_water_mask,
                    water_mask_threshold_db=args.water_mask_threshold_db,
                    scale_m=args.scale_m,
                    dry_run=args.dry_run,
                )
            ]
        else:
            missing = [
                name
                for name in ("start_date", "end_date", "orbit_relative", "pass_direction")
                if getattr(args, name) is None
            ]
            if missing:
                missing_flags = ", ".join(f"--{name.replace('_', '-')}" for name in missing)
                raise ValueError(
                    "batch mode requires " + missing_flags
                )
            scenes = discover_scene_specs(
                aoi_geojson=aoi_geojson,
                orbit_relative=args.orbit_relative,
                pass_direction=args.pass_direction,
                start_date=args.start_date,
                end_date=args.end_date,
            )
            results = backfill_scene_batch(
                reservoir_id=args.reservoir,
                scenes=scenes,
                aoi_geojson=aoi_geojson,
                out_root=out_root,
                catalog_path=args.catalog,
                include_water_mask=not args.no_water_mask,
                water_mask_threshold_db=args.water_mask_threshold_db,
                scale_m=args.scale_m,
                dry_run=args.dry_run,
            )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    action = "would write" if args.dry_run else "wrote"
    for result in results:
        if result.skipped:
            print(f"skipped existing: {result.reservoir_id} {result.acquisition_date}")
            continue
        print(f"{action}: {result.vv_path}")
        print(f"{action}: {result.vh_path}")
        if result.water_mask_path is not None:
            print(f"{action}: {result.water_mask_path}")
        if result.registered:
            print(f"registered: {result.reservoir_id} {result.acquisition_date} {result.scene_id}")
    print(f"scenes: {len(results)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
