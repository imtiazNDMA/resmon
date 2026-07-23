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

/** Live EE tile template for one acquisition (`/reservoirs/{id}/sar-tiles`). */
export interface SarTile {
  tile_url: string;
  expires_at: string;
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

/** Properties on `/geojson/water-extent` features (latest real SAR mask per reservoir). */
export interface WaterExtentProperties {
  reservoir_id: string;
  name: string;
  surface_area_km2: number;
  acquisition_date: string;
}

/** Properties on `/geojson/reservoirs` marker features. */
export interface ReservoirMarkerProperties {
  reservoir_id: string;
  name: string;
  frl_m: number;
  risk_level: RiskLevel | null;
  release_probability: number | null;
}
