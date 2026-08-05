export type HydrologicMapProductId =
  | "fleet_overview"
  | "reservoir_catchment"
  | "interactive_analysis"
  | "static_export";

export type HydrologicLayerRole =
  | "catchment_divide"
  | "sub_basin"
  | "main_stem"
  | "tributary"
  | "reservoir_max_extent"
  | "reservoir_current_extent"
  | "dam_point"
  | "terrain";

export const HYDROLOGIC_MAP_PRODUCTS: Array<{
  id: HydrologicMapProductId;
  label: string;
  purpose: string;
}> = [
  {
    id: "fleet_overview",
    label: "Fleet overview",
    purpose: "Regional context across the pilot reservoirs with major basins and main rivers only.",
  },
  {
    id: "reservoir_catchment",
    label: "Selected-reservoir catchment",
    purpose: "Default operational view for one dam's upstream contributing area.",
  },
  {
    id: "interactive_analysis",
    label: "Interactive analysis",
    purpose: "Zoomed analyst view with sub-basins, flow paths, forcing overlays, and tooltips.",
  },
  {
    id: "static_export",
    label: "Static export",
    purpose: "Later report/situation-briefing map with export-quality geometry and legend.",
  },
];

export const HYDROLOGIC_SOURCE_HIERARCHY = {
  contributingArea: "MERIT Hydro flow direction/accumulation",
  basinDisplayUnits: "HydroSHEDS HydroBASINS",
  drainageNetwork: "HydroRIVERS or MERIT Hydro-derived stream vectors",
  reservoirExtent: "JRC Global Surface Water max extent + Sentinel-1 SAR current extent",
  terrain: "MERIT DEM, SRTM, or Copernicus DEM hillshade/elevation",
} as const;

export const HYDROBASINS_LEVEL_POLICY = {
  regionalContext: "hybas_5_or_6",
  reservoirOverview: "hybas_7",
  zoomedAnalysis: "hybas_8_or_9_when_performance_allows",
} as const;

export const HYDROLOGIC_LAYER_STYLES: Record<HydrologicLayerRole, { color: string; note: string }> = {
  catchment_divide: {
    color: "#d9a45b",
    note: "Warm drainage-divide outline so users do not read it as water.",
  },
  sub_basin: {
    color: "#8c93a8",
    note: "Muted basin fill/outline; highlight only on hover or thematic overlay.",
  },
  main_stem: {
    color: "#59b7ff",
    note: "Bright, wider blue/cyan stroke for primary flow path.",
  },
  tributary: {
    color: "#63d7ff",
    note: "Thinner blue/cyan stroke, revealed progressively by zoom/stream order.",
  },
  reservoir_max_extent: {
    color: "#59b7ff",
    note: "Muted outline for historical/max reservoir footprint.",
  },
  reservoir_current_extent: {
    color: "#1f6db3",
    note: "Filled current SAR-derived water extent.",
  },
  dam_point: {
    color: "#dbe7f3",
    note: "High-contrast marker at the control/outlet point.",
  },
  terrain: {
    color: "#71818f",
    note: "Low-contrast hillshade/elevation tint behind hydrology layers.",
  },
};

export const HYDROLOGIC_SIMPLIFICATION_POLICY = {
  internalRaw: 0,
  webVectorDegrees: 0.0001,
  regionalLowZoomDegrees: 0.001,
  exportVectorDegrees: 0.00005,
  requirement: "Use topology-preserving simplification and never break NEXT_DOWN drainage topology.",
} as const;

export const HYDROBASINS_CARTOGRAPHIC_WARNING =
  "HydroBASINS are display/aggregation units; validate true dam-specific contributing area with MERIT Hydro and published basin areas.";
