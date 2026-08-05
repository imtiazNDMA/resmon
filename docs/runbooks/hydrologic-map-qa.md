# Hydrologic Map QA Notes

Phase 8A serves static hydrologic cartography for the pilot reservoirs from persisted
PostGIS layers:

- `reservoir.catchment_geom`: selected upstream catchment boundary.
- `catchment_subbasin`: HydroBASINS-derived sub-basin display/topology units.
- `catchment_flowline`: HydroRIVERS v10 Asia drainage vectors clipped to each catchment.
- `district_boundary`: simplified administrative context boundaries.
- `hydrologic_layer_provenance`: source/version/processing limitations shown in the UI.

## Automated Checks

Run:

```powershell
uv run python scripts/qa_hydrologic_layers.py
```

Current checks cover:

- catchment area sanity, with Gobind Sagar compared to a published BBMB reference.
- sub-basin count, headwaters, duplicate `HYBAS_ID`, invalid geometries, and topology outlet count.
- HydroRIVERS flowline presence, max stream order, main-stem count, and invalid geometries.

Expected current shape:

- each pilot has exactly one external sub-basin outlet.
- `missing_downstream=0` after accounting for that external outlet.
- `invalid=0` and `invalid_flowlines=0`.

## Manual Visual QA

For each pilot reservoir, check overview, catchment, and tributary zoom levels:

- catchment divide encloses the displayed drainage network.
- major rivers visually converge toward the reservoir/dam area.
- sub-basin outlines do not dominate the drainage network.
- district boundaries remain low-priority context.
- current SAR water extent and dam marker remain legible over the hydrologic layers.

## Known Limitations

- HydroBASINS polygons are cartographic and aggregation units, not a dam-point flow-direction
  delineation. MERIT Hydro validation is still required before claiming outlet-accurate
  contributing area.
- HydroRIVERS lines are clipped to the catchment boundary and inherit HydroRIVERS topology;
  v1 does not snap the dam point to the nearest flowline or correct local outlet geometry.
- DEM-derived hillshade/elevation/slope tiles are not locally generated yet. The interactive
  view uses a topo basemap as the v1 terrain context.
- Pong and Thein published catchment-area references still need sourcing for automated area
  ratio checks.
- High-mountain snow/glacier/rainfall products have coarse resolution and uncertainty; they
  should explain forecast context, not directly infer release events.
