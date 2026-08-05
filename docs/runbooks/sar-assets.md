# Runbook — Local SAR assets

Local SAR serving uses GeoTIFF/COG files on disk plus a SQLite metadata catalog. The API renders and caches PNG XYZ tiles from those rasters for fast timeline playback.

## Storage

- `SAR_COG_ROOT` controls the GeoTIFF/COG storage root.
- Default: `data/sar_cog`.
- Relative paths are resolved from the repository root.
- Rendered PNG tiles live under `.cache/sar_rasters`.
- Catalog metadata lives in `.cache/sar_assets.sqlite`.

Expected COG layout:

```text
${SAR_COG_ROOT}/{reservoir_id}/{date}/vv.tif
${SAR_COG_ROOT}/{reservoir_id}/{date}/vh.tif
${SAR_COG_ROOT}/{reservoir_id}/{date}/water_mask.tif
```

## Register Existing Rasters

```bash
uv run python scripts/register_sar_assets.py \
  --reservoir pong \
  --date 2020-01-05 \
  --scene-id S1A_TEST \
  --vv data/sar_cog/pong/2020-01-05/vv.tif \
  --vh data/sar_cog/pong/2020-01-05/vh.tif \
  --water-mask data/sar_cog/pong/2020-01-05/water_mask.tif
```

Registration validates the rasters, records geographic bounds, and stores file size plus SHA-256 checksums. If a file changes after registration, the API treats that catalog row as unavailable until it is re-registered.

## Backfill From Earth Engine

Single known scene:

```bash
uv run python scripts/backfill_sar_assets.py \
  --reservoir pong \
  --date 2020-01-05 \
  --scene-id S1A_TEST \
  --aoi data/backfill/aoi_pong.geojson
```

Date-range discovery and backfill:

```bash
uv run python scripts/backfill_sar_assets.py \
  --reservoir pong \
  --start-date 2020-01-01 \
  --end-date 2020-02-01 \
  --orbit-relative 12 \
  --pass-direction ASC \
  --aoi data/backfill/aoi_pong.geojson
```

Use `--dry-run` first to confirm target paths and scene count without downloading or writing catalog rows.

## Prewarm Tiles

Prewarm one acquisition/composite/zoom range:

```bash
uv run python scripts/prewarm_sar_tiles.py \
  --reservoir pong \
  --date 2020-01-05 \
  --composite vh \
  --min-zoom 8 \
  --max-zoom 10
```

Prewarm the latest local acquisition plus nearby prior dates for demos:

```bash
uv run python scripts/prewarm_sar_tiles.py \
  --reservoir pong \
  --composite vh \
  --min-zoom 8 \
  --max-zoom 10 \
  --latest-nearby 2
```

## Cache Operations

Report rendered PNG cache size:

```bash
uv run python scripts/sar_tile_cache.py --stats
```

Delete oldest PNG tiles until the cache is at or below a target size:

```bash
uv run python scripts/sar_tile_cache.py --cleanup-max-mb 512
```

## Metrics

The API exposes in-process SAR tile serving counters:

```text
GET /metrics/sar-tiles
```

Counters include rendered PNG cache hits, local COG renders, Earth Engine fallbacks, and total/average tile render latency. These reset when the API process restarts.

## Object Storage / CDN Path

The current v1 layout intentionally keeps COGs and rendered tiles on local disk. The catalog stores paths rather than bytes, so moving either artifact class later can be done without changing the reservoir API shape:

- Move `SAR_COG_ROOT` to mounted object storage or a synced volume first.
- Move `.cache/sar_rasters` behind object storage/CDN when cache hit traffic grows.
- Keep SQLite for local/dev; use the app database or object metadata index if multiple API replicas need shared catalog writes.
