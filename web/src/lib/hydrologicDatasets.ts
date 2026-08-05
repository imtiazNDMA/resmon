export type HydrologicDatasetCategory =
  | "terrain"
  | "basins"
  | "flow_network"
  | "reservoir_geometry"
  | "hydromet_dynamic"
  | "context"
  | "provenance";

export type HydrologicDatasetPriority = "primary" | "cross_check" | "fallback" | "context";

export interface HydrologicDatasetSpec {
  id: string;
  category: HydrologicDatasetCategory;
  priority: HydrologicDatasetPriority;
  label: string;
  source: string;
  purpose: string;
  requiredFields: string[];
  limitations: string[];
}

export const HYDROLOGIC_DATASETS: HydrologicDatasetSpec[] = [
  {
    id: "merit_dem_or_srtm",
    category: "terrain",
    priority: "primary",
    label: "MERIT DEM / SRTM / Copernicus DEM",
    source: "MERIT DEM preferred; SRTM or Copernicus DEM acceptable for v1 terrain context",
    purpose: "Terrain, hillshade, slope, aspect, and elevation tint for HydroSHEDS-style maps.",
    requiredFields: ["elevation_m", "resolution_m", "source_version"],
    limitations: ["DEM voids and steep terrain artifacts can affect hillshade and slope."],
  },
  {
    id: "hydrobasins",
    category: "basins",
    priority: "primary",
    label: "HydroSHEDS HydroBASINS",
    source: "WWF/HydroSHEDS/v1/Basins/hybas_*",
    purpose: "Cartographic basin display units and upstream topology scaffold.",
    requiredFields: ["HYBAS_ID", "NEXT_DOWN", "MAIN_BAS", "SUB_AREA", "UP_AREA"],
    limitations: ["Display/aggregation units only; validate dam-specific catchment with MERIT Hydro."],
  },
  {
    id: "merit_hydro",
    category: "basins",
    priority: "primary",
    label: "MERIT Hydro",
    source: "MERIT Hydro flow direction / flow accumulation rasters",
    purpose: "Authority for dam-specific contributing area and outlet/routing validation.",
    requiredFields: ["flow_direction", "flow_accumulation", "upstream_area"],
    limitations: ["Dam point may need manual snap/override to the correct flow accumulation cell."],
  },
  {
    id: "hydrorivers_or_merit_vectors",
    category: "flow_network",
    priority: "primary",
    label: "HydroRIVERS or MERIT-derived stream vectors",
    source: "HydroRIVERS / vectorized MERIT Hydro drainage network",
    purpose: "Visible river and tributary hierarchy clipped to each reservoir catchment.",
    requiredFields: ["geometry", "upstream_area", "stream_order", "downstream_id"],
    limitations: ["Line direction and network connectivity must be QA-checked before animation."],
  },
  {
    id: "jrc_global_surface_water",
    category: "reservoir_geometry",
    priority: "primary",
    label: "JRC Global Surface Water max extent",
    source: "JRC/GSW1_4/GlobalSurfaceWater",
    purpose: "Historical/max reservoir footprint and AOI bootstrap around the dam point.",
    requiredFields: ["max_extent", "occurrence", "seasonality"],
    limitations: ["Historical max water extent is not the same as current SAR water extent."],
  },
  {
    id: "sentinel1_water_extent",
    category: "reservoir_geometry",
    priority: "primary",
    label: "Sentinel-1 SAR current water extent",
    source: "Platform SAR water extraction pipeline",
    purpose: "Current reservoir water fill shown distinctly from historical/max extent.",
    requiredFields: ["water_mask_geom", "acquisition_date", "area_confidence"],
    limitations: ["Extraction confidence and layover/shadow flags must be surfaced honestly."],
  },
  {
    id: "era5_land",
    category: "hydromet_dynamic",
    priority: "primary",
    label: "ERA5-Land precipitation, temperature, SWE",
    source: "ECMWF ERA5-Land via GEE/xee or equivalent backend",
    purpose: "Primary high-altitude rainfall, temperature, snow, and melt-context forcing.",
    requiredFields: ["precipitation", "temperature_2m", "snow_water_equivalent"],
    limitations: ["Reanalysis uncertainty remains high in complex Himalayan terrain."],
  },
  {
    id: "gpm_imerg",
    category: "hydromet_dynamic",
    priority: "cross_check",
    label: "GPM IMERG precipitation",
    source: "NASA GPM IMERG",
    purpose: "Satellite precipitation cross-check for ERA5-Land precipitation.",
    requiredFields: ["precipitation"],
    limitations: ["Mountain precipitation and snowfall phase uncertainty can be significant."],
  },
  {
    id: "modis_snow",
    category: "hydromet_dynamic",
    priority: "primary",
    label: "MODIS snow cover",
    source: "MODIS NDSI snow-cover products",
    purpose: "Snow-cover area and snowline context for upper catchments.",
    requiredFields: ["snow_cover", "cloud_or_quality_flag"],
    limitations: ["Cloud, terrain shadow, and forest cover can obscure snow state."],
  },
  {
    id: "gfs_forecast",
    category: "hydromet_dynamic",
    priority: "primary",
    label: "NOAA GFS forecast forcing",
    source: "NOAA/GFS0P25 or equivalent forecast feed",
    purpose: "Forward-looking precipitation and temperature over the 1-14 day forecast horizon.",
    requiredFields: ["forecast_precipitation", "forecast_temperature_2m", "run_time"],
    limitations: ["Forecast forcing must be point-in-time selected to avoid leakage in backtests."],
  },
  {
    id: "admin_boundaries_context",
    category: "context",
    priority: "context",
    label: "Administrative and settlement context",
    source: "Bundled district/state/country boundaries and optional settlement layers",
    purpose: "Low-opacity context only; hydrology remains the visual hierarchy.",
    requiredFields: ["geometry", "name_or_id", "source_version"],
    limitations: ["Do not let political boundaries compete visually with drainage structure."],
  },
  {
    id: "layer_provenance",
    category: "provenance",
    priority: "primary",
    label: "Hydrologic layer provenance metadata",
    source: "Pipeline-generated metadata for every prepared hydrologic layer",
    purpose: "Audit source dataset, version, resolution, processing date, projection, and limitations.",
    requiredFields: ["dataset_id", "version", "resolution", "processed_at", "projection", "limitations"],
    limitations: ["Missing provenance should block production promotion for derived map layers."],
  },
];

export const datasetIdsForCategory = (category: HydrologicDatasetCategory) =>
  HYDROLOGIC_DATASETS.filter((dataset) => dataset.category === category).map(
    (dataset) => dataset.id,
  );
