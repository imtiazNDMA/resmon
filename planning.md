# Local SAR Serving Plan

Goal: make SAR timeline playback fast, reliable, and zoomable by serving imagery locally instead of depending on Earth Engine during interactive map use.

## Architecture Decision

- Use the local database as a SAR asset catalog, not as the pixel store.
- Store SAR rasters as local Cloud-Optimized GeoTIFFs (COGs) or equivalent georeferenced raster files on disk.
- Serve Leaflet XYZ PNG tiles from the API.
- Cache rendered PNG tiles on disk after first render.
- Keep Earth Engine as an ingestion/backfill source and fallback while local coverage is incomplete.

Why not DB BLOBs for imagery:

- Zoomable rasters need windowed reads by tile bounds; COG files are built for that.
- Databases are useful for metadata, indexing, and availability checks, but less efficient for streaming raster bytes.
- File/object storage can later move to S3/Azure Blob/CDN without changing the catalog API.

## Target Local Layout

```text
data/sar_cog/{reservoir_id}/{date}/vv.tif
data/sar_cog/{reservoir_id}/{date}/vh.tif
data/sar_cog/{reservoir_id}/{date}/water_mask.tif
.cache/sar_rasters/{reservoir_id}/{date}/{composite}/{z}/{x}/{y}.png
.cache/sar_assets.sqlite
```

## Target Request Flow

1. Frontend requests `/api/reservoirs/{rid}/sar-tiles?date=...&composite=...`.
2. API checks the local SAR asset catalog.
3. If local assets cover the requested acquisition/composite, API returns the same local XYZ tile URL template.
4. Browser requests `/api/reservoirs/{rid}/sar-tile-raster/{date}/{z}/{x}/{y}?composite=...`.
5. Raster endpoint checks rendered PNG tile cache.
6. If missing and local COGs exist, API reads the COG window, renders the composite tile, stores PNG cache, and returns it.
7. If no local asset exists, API falls back to Earth Engine and caches the proxied PNG as it does today.

## Phase 1: Local Catalog Foundation

- [x] Document the local SAR architecture and phased rollout.
- [x] Add a local SAR asset catalog module backed by SQLite.
- [x] Define canonical fields: reservoir id, acquisition date, scene id, VV path, VH path, water-mask path, bounds, min/max zoom, status.
- [x] Add catalog lookup tests.
- [ ] Keep current Earth Engine fallback unchanged.

## Phase 2: API Source Selection

- [x] Have `/sar-tiles` check the local catalog before minting Earth Engine map ids.
- [x] Return the existing raster-proxy tile URL for both local and Earth Engine sources.
- [x] Add a response field such as `source: "local" | "earth_engine"` for observability.
- [x] Serve already-rendered PNG tiles from the local cache before minting Earth Engine map ids.
- [x] Add API tests for local asset available and cached PNG serving.
- [x] Add API tests for local asset missing and invalid composite.

## Phase 3: Local COG Rendering

- [x] Add an explicit local-renderer seam before Earth Engine fallback.
- [x] Cache successfully rendered local PNG tiles under `.cache/sar_rasters`.
- [x] Add raster dependencies after confirming platform support (`rasterio`/GDAL or a lighter tile server dependency).
- [x] Implement XYZ tile bounds to raster window conversion.
- [x] Render supported composites from local VV/VH/water-mask rasters.
- [x] Preserve existing color ramps and composite IDs.
- [x] Add unit tests for cache hit, missing asset fallback, and composite validation.

## Phase 4: Ingestion / Backfill

- [x] Add a CLI script to register existing local SAR assets for a reservoir/date.
- [x] Add a CLI script to backfill local SAR assets for a known scene from Earth Engine.
- [x] Add date-range scene discovery and batch backfill from Earth Engine.
- [x] Export/download VV and VH acquisitions into local GeoTIFF paths.
- [x] Generate or persist water masks where available.
- [x] Upsert catalog rows after files are verified on disk.
- [x] Add a `--dry-run` mode for validating existing rasters without catalog writes.
- [x] Add a `--dry-run` mode that reports target paths for one Earth Engine scene.
- [x] Add a `--dry-run` mode that reports target paths and scene count for date-range Earth Engine backfill.

## Phase 5: Coverage and Prewarm

- [x] Add a manifest endpoint that reports which dates/composites are local.
- [x] Add frontend API typing/client access for local SAR coverage.
- [x] Add tile prewarm command for selected reservoir/date/composite/zoom ranges.
- [x] Prewarm the latest date plus nearby timeline dates for demos.
- [x] Add cache size reporting and cleanup policy.

## Phase 6: Production Hardening

- [x] Move COG storage behind a configurable root path.
- [x] Add checksums/file-size validation in the catalog.
- [x] Add metrics: local hit, rendered hit, Earth Engine fallback, tile render latency.
- [x] Add operational docs for refreshing SAR assets.
- [x] Consider moving rendered tiles and/or COGs to object storage/CDN.

## Open Questions

- Which zoom levels are operationally required for reservoir monitoring?
- Do we need every historical acquisition locally, or only recent acquisitions plus demo years?
- Should the water mask be stored as a raster band, separate COG, or derived on render?
- Is local SQLite enough for the catalog, or should it use the existing app database migration path?
