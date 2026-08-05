# PMD Weather Persistence and Aggregation Contract

Phase 8C.6 governs whether PMD weather layers remain display-only cache responses or become persisted modelling inputs.

## Current Decision

All PMD/FFD datasets integrated in Phase 8C remain cache-only display/context layers until a separate validation slice proves unit alignment, spatial representativeness, and forecast skill impact.

## Dataset Classes

| Dataset | Current handling | Persistence decision | Modelling decision |
| --- | --- | --- | --- |
| PMD Monitor stations | Backend cache only | Do not persist raw point observations | Do not feed model forcing |
| PMD NWFC observations | Backend cache only | Do not persist raw point observations | Do not feed model forcing |
| PMD warnings/monsoon | Backend cache only | Persist later only if warning history product is defined | Do not feed release-risk directly |
| PMD GLOF observations | Backend cache only | Persist later only with station identity/cadence contract | Do not feed model forcing |
| PMD lightning | Backend cache only | Do not persist unless storm-history product is defined | Do not feed model forcing |
| FFD waterlevels | Backend cache only | Persist later only with river gauge identity/cadence contract | Do not use as reservoir release ground truth |
| PMD prediction rasters | Disk metadata/image cache only once validated | Persist only rendered PNG/JSON cache artifacts | Do not write to forcing tables until aggregation validation passes |

## Aggregation Gate

PMD forecast rasters may be promoted into `forecast_forcing` only after all conditions are met:

- Element is `product-ready` in `docs/contracts/pmd-forecast-raster-discovery.md`.
- CRS, bounds, nodata, units, and accumulation window are documented from real raster evidence.
- Catchment clipping/aggregation is tested against known geometries.
- Aggregated values carry source, element, run time, forecast time, accumulation window, cache status, and raster evidence checksum.
- Walk-forward backtests are rerun before claiming any release-risk skill improvement.

Observed PMD point/rainfall summaries may be promoted into `catchment_forcing` only after cadence and spatial representativeness are documented. Until then, existing ERA5/Open-Meteo/GFS-style forcing remains the modelling boundary.

## Provenance

Dynamic weather provenance should use dedicated weather freshness metadata in API responses and future weather tables. Do not reuse `hydrologic_layer_provenance` for live PMD weather because it describes static map-processing provenance, not dynamic upstream freshness.

Future forcing rows derived from PMD must include source-version/freshness fields sufficient to distinguish PMD-derived inputs from ERA5/Open-Meteo/GFS inputs.
