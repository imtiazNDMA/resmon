# Hydrologic Map Dataset Contract

This contract defines the dataset inventory required to build HydroSHEDS-style
reservoir catchment maps. It implements Phase 8A.2 and follows ADR-0008.

## Required Dataset Groups

| Group | Primary datasets | Purpose | Required provenance |
| --- | --- | --- | --- |
| Terrain | MERIT DEM preferred; SRTM/Copernicus DEM acceptable | Hillshade, slope, aspect, elevation tint | source, version, resolution, processing date, projection, limitations |
| Basin polygons | HydroSHEDS HydroBASINS | Display/aggregation units and `NEXT_DOWN` topology scaffold | HydroBASINS level, source version, simplification tolerance, topology QA status |
| Contributing area authority | MERIT Hydro | Validate true dam-specific contributing area and outlet/routing | flow-direction version, flow-accumulation version, snap/override notes |
| Flow network | HydroRIVERS or MERIT-derived vectors | Visible main stem and tributary hierarchy | stream-order method, upstream-area field, direction/connectivity QA |
| Reservoir geometry | JRC Global Surface Water, platform SAR water extent, dam point | Max/historical reservoir footprint and current SAR water state | source date/version, acquisition date, extraction confidence, AOI version |
| Hydromet dynamic context | ERA5-Land, GPM IMERG, MODIS snow, NOAA GFS | Rainfall, snow, temperature, and forecast forcing overlays | product version, time range, aggregation method, freshness, quality flags |
| Political/context | District/state/country boundaries and optional settlements | Low-opacity orientation context | source, version, simplification tolerance |
| Provenance metadata | Pipeline-generated layer provenance | Auditability for every prepared hydrologic layer | dataset id, version, resolution, processed-at timestamp, projection, limitations |

## Rules

- HydroBASINS polygons are cartographic/aggregation units, not final hydrologic proof.
- MERIT Hydro validation is required before promoting a dam-specific contributing area to production.
- Terrain/context layers must not visually dominate water and drainage layers.
- Current SAR water extent must be visually distinct from JRC historical/max reservoir extent.
- Hydromet overlays must carry freshness and source-product labels.
- Missing provenance blocks production promotion for derived hydrologic map layers.

## Frontend Mirror

The frontend mirror of this contract is `web/src/lib/hydrologicDatasets.ts`. Tests in
`web/src/lib/hydrologicDatasets.test.ts` ensure every required dataset group remains
represented while the map implementation grows.
