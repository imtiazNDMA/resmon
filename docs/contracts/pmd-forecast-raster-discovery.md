# PMD Forecast Raster Discovery Contract

Phase 8C.4 tracks PMD Monitor prediction rasters before they become product layers or model inputs. Candidate codes are not treated as confirmed until a live metadata response and at least one downloaded raster have been inspected.

## Status Vocabulary

- `candidate`: code seen in PMD research notes or portal labels, not yet verified live.
- `metadata-confirmed`: `/api/modelTimeList` returned current runs for the exact `data_type` + `element` pair.
- `raster-confirmed`: one GeoTIFF/PNG source artifact was downloaded and inspected for CRS, extent, nodata, band count, unit, and value range.
- `product-ready`: color ramp, accumulation window, frame cadence, cache policy, and limitations are documented and tested.

## Candidate Elements

| Frontend key | data_type | element | Label | Unit | Accumulation | Status | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `pmd_pred_hourtpe` | `WRFPRS` | `HOURTPE` | Hourly precipitation | `mm` | 1h | `candidate` | Must confirm live metadata and raster values before UI exposure. |
| `pmd_pred_sixtpe` | `WRFPRS` | `SIXTPE` | 6h precipitation | `mm` | 6h | `candidate` | Must confirm whether accumulation resets per frame. |
| `pmd_pred_twelvetpe` | `WRFPRS` | `TWELVETPE` | 12h precipitation | `mm` | 12h | `candidate` | Must confirm time labels and accumulation semantics. |
| `pmd_pred_daytpe` | `WRFPRS` | `DAYTPE` | 24h precipitation | `mm` | 24h | `candidate` | Must confirm whether this is daily total or rolling 24h. |

## Required Evidence Per Element

- Live metadata response from `/api/modelTimeList?data_type=<data_type>&element=<element>` with request timestamp.
- Discovery summary from `uv run python scripts/discover_pmd_prediction_elements.py --element-key <key>`.
- Exact model run ID/time and frame list used for inspection.
- One downloaded raster artifact path or checksum.
- Raster evidence from `uv run python scripts/inspect_pmd_prediction_raster.py <path> --element-key <key>`.
- CRS and bounds.
- Band count and data type.
- Nodata value and how it maps to transparent pixels.
- Pixel value min/max/percentiles after nodata removal.
- Unit and accumulation window evidence.
- Official PMD color ramp source, or explicit note that the ramp is project-defined.
- Known caveats, including stale upstream data, missing frames, and model resolution limits.

## Promotion Rules

- A candidate may not appear in frontend controls until it reaches `product-ready`.
- PMD forecast raster values may not be written to `catchment_forcing` or `forecast_forcing` until aggregation units, accumulation windows, and backtest impact are validated.
- Raster discovery is provenance only; it does not directly observe release events and does not alter release-risk without a forecast backtest.

## Operator Commands

```powershell
uv run python scripts/discover_pmd_prediction_elements.py --element-key pmd_pred_hourtpe
uv run python scripts/inspect_pmd_prediction_raster.py path\to\downloaded.tif --element-key pmd_pred_hourtpe
uv run python scripts/cleanup_pmd_prediction_cache.py --older-than-days 14 --delete
```
