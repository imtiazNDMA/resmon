import type {
  FeatureCollection as GeoJSONFeatureCollection,
  GeoJsonProperties,
  Geometry,
} from "geojson";

export type GeoFC<P = GeoJsonProperties> = GeoJSONFeatureCollection<Geometry, P>;

export type RiskLevel = "Low" | "Watch" | "Warning" | "Imminent";

export interface Reservoir {
  reservoir_id: string;
  name: string;
  basin: string;
  frl_m: number;
  live_capacity_bcm: number;
  is_active: boolean;
}

export interface Status {
  reservoir_id: string;
  as_of: string;
  pct_filled: number;
  level_m: number | null;
  live_storage_bcm: number | null;
  risk_level: RiskLevel | null;
  release_probability: number | null;
  estimated_lead_time_days: number | null;
  last_acquisition_date: string | null;
  data_age_days: number | null;
  stale: boolean;
}

/** One non-stub SAR acquisition (`/reservoirs/{id}/acquisitions`). */
export interface Acquisition {
  date: string;
  historical_date: string | null;
  area_km2: number;
  confidence: number;
  live_storage_bcm: number | null;
  level_m: number | null;
  pct_filled: number | null;
  surface_area_correlation: number | null;
  is_extrapolated: boolean;
}

/** SAR tile template for one acquisition (`/reservoirs/{id}/sar-tiles`). */
export interface SarTile {
  tile_url: string;
  expires_at: string;
  composite: string;
  source: "local" | "earth_engine";
}

export interface SarAssetManifestEntry {
  reservoir_id: string;
  acquisition_date: string;
  scene_id: string;
  composites: string[];
  bounds: number[] | null;
  min_zoom: number;
  max_zoom: number;
}

/** One day of catchment rainfall (`/reservoirs/{id}/rainfall`). */
export interface RainfallPoint {
  date: string;
  precip_mm: number | null;
}

export interface MetForcing {
  reservoir_id: string;
  as_of: string | null;
  precip_7d_mm: number | null;
  antecedent_precip_index_mm: number | null;
  snow_cover_pct: number | null;
  degree_day_melt_mm_day: number | null;
  evaporation_mm_day: number | null;
}

/** Properties on `/geojson/aoi` features. */
export interface AoiProperties {
  reservoir_id: string;
  name: string;
  aoi_version: string;
}

/** Properties on `/geojson/catchment` features (HydroSHEDS HydroBASINS). */
export interface CatchmentProperties {
  reservoir_id: string;
  name: string;
  version: string | null;
}

/** Properties on `/geojson/subbasins` features — the un-dissolved form of the catchment.
 *  `is_headwater` marks a basin nothing drains into, i.e. the upper catchment. */
export interface SubBasinProperties {
  reservoir_id: string;
  hybas_id: number;
  next_down: number;
  is_headwater: boolean;
  version: string;
}

/** Properties on `/geojson/flow-edges` features — topology-derived display paths
 *  from each sub-basin toward its downstream neighbour or the dam point. */
export interface FlowEdgeProperties {
  reservoir_id: string;
  from_hybas_id: number;
  to_hybas_id: number | null;
  is_headwater: boolean;
  distance_to_reservoir_km: number | null;
  routing_lag_days: number | null;
  version: string;
}

/** Properties on `/geojson/hydrologic/flowlines` features — clipped river/drainage
 * vectors for the selected reservoir catchment. */
export interface FlowlineProperties {
  reservoir_id: string;
  flowline_id: number;
  downstream_id: number | null;
  stream_order: number | null;
  upstream_area_km2: number | null;
  length_km: number | null;
  is_main_stem: boolean;
  source_dataset: string;
  version: string;
}

export interface HydrologicLayerProvenance {
  reservoir_id: string;
  layer_name: string;
  source_dataset: string;
  source_version: string | null;
  source_date: string | null;
  resolution_m: number | null;
  processed_at: string;
  processing_version: string;
  simplification_tolerance_deg: number | null;
  projection: string;
  limitations: string;
  metadata: Record<string, unknown>;
}

/** Properties on `/geojson/water-extent` features (latest real SAR mask per reservoir). */
export interface WaterExtentProperties {
  reservoir_id: string;
  name: string;
  surface_area_km2: number;
  acquisition_date: string;
}

/** Properties on `/geojson/districts` features. */
export interface DistrictBoundaryProperties {
  district_id: number;
  bbox: number[];
}

/** Properties on `/geojson/reservoirs` marker features. */
export interface ReservoirMarkerProperties {
  reservoir_id: string;
  name: string;
  frl_m: number;
  risk_level: RiskLevel | null;
  release_probability: number | null;
}

export interface PmdFreshnessProperties {
  source: string;
  source_timestamp: string | null;
  fetched_at: string;
  cache_status: string;
  stale: boolean;
  ttl_seconds: number;
}

export interface PmdStationObservationProperties extends PmdFreshnessProperties {
  station_id: string | null;
  code: string | null;
  name: string | null;
  station_type: string | null;
  date_time: string | null;
  temperature_c: number | null;
  humidity_pct: number | null;
  pressure_hpa: number | null;
  wind_speed_mps: number | null;
  wind_direction_deg: number | null;
  rain_1h_mm: number | null;
  rain_6h_mm: number | null;
  rain_24h_mm: number | null;
  visibility_km: number | null;
  status: boolean | null;
  warn_temp: string | null;
  warn_wind: string | null;
  warn_rain: string | null;
  warn_vis: string | null;
}

export interface PmdWarningProperties extends PmdFreshnessProperties {
  warning_id: string | null;
  severity: string | null;
  hazard: string | null;
  model: string | null;
  forecast_time: string | null;
  data_time: string | null;
  message: string | null;
  area_name: string | null;
}

export interface PmdMonsoonProperties extends PmdFreshnessProperties {
  warning_id: string | null;
  severity: string | null;
  data_type: string | null;
  data_time: string | null;
  message: string | null;
  forecast: unknown;
}
