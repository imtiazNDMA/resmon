# Hydrologic map foundation: HydroBASINS as display units, MERIT Hydro as authority

## Context

The map needs to explain how upstream rainfall and snowmelt can influence each
reservoir's forecast trajectory and inherited release-risk. A HydroSHEDS-style map is
useful only if the cartography does not overclaim the hydrology. HydroBASINS polygons
are excellent basin display units, but a dam point often does not sit exactly on a
HydroBASINS outlet. A containment-only basin pick can over-count or under-count the
true contributing area.

## Decision

- **Map products.** Support four products: a fleet overview, a selected-reservoir
  catchment view, an interactive analysis map, and a later print/export static map for
  situation briefings. The interactive selected-reservoir map is the first production
  target.
- **Source hierarchy.** MERIT Hydro flow direction/accumulation is the authority for
  dam-specific contributing area and routing when available. HydroBASINS/HydroSHEDS are
  basin display and aggregation units. HydroRIVERS or MERIT-derived vectors provide the
  visible drainage network. JRC Global Surface Water and SAR masks provide reservoir
  extent/current water state. DEM hillshade/elevation provides terrain context.
- **HydroBASINS levels.** Use level 5-6 for regional/fleet context, level 7 for the
  reservoir catchment overview, and level 8-9 only for zoomed analysis where feature
  count and topology quality remain usable.
- **Topology caveat.** HydroBASINS polygons are cartographic/aggregation units, not the
  final proof of true contributing area. Each reservoir catchment must be validated
  against MERIT Hydro flow accumulation where possible and against published catchment
  area references.
- **Styling semantics.** Catchment divides must not look like water. Use warm/sand
  outlines for drainage boundaries, blue/cyan only for water/flow, muted terrain tints
  for physiography, and high-contrast dam/reservoir markers. Main stems are wider than
  tributaries; max reservoir extent is an outline, current SAR water extent is a fill.
- **Simplification tolerances.** Persist raw/internal geometry separately from served
  geometry. Use topology-preserving simplification for web display and a stricter
  export-quality path. Default web tolerances should be around 0.0001 degrees for
  vectors already served by the API, with larger cartographic simplification allowed
  only for low-zoom regional layers. Never simplify in a way that breaks `NEXT_DOWN`
  topology or disconnects the visible drainage network.

## Consequences

- The first build can safely use existing HydroBASINS `NEXT_DOWN` topology as a visual
  scaffold while labeling routing lag as a proxy, not calibrated hydraulics.
- The later terrain/flowline work has a clear data authority: MERIT Hydro validates the
  catchment, HydroBASINS structures the visual aggregation, and HydroRIVERS/MERIT lines
  make drainage legible.
- The UI can share one stable vocabulary for layer names, colors, and source warnings,
  avoiding one-off map styling that confuses catchment boundaries with rivers.
- Rejected: using only the basin containing the dam, treating HydroBASINS as the final
  hydrologic truth, and styling all blue lines/polygons as if they were observed water.
