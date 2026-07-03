import type {
  FeatureCollection as GeoJSONFeatureCollection,
  GeoJsonProperties,
  Geometry,
} from "geojson";

export type GeoFC<P = GeoJsonProperties> = GeoJSONFeatureCollection<Geometry, P>;

/** Properties on `/geojson/water-extent` features (latest Sentinel-1 mask per reservoir). */
export interface WaterExtentProperties {
  reservoir_id: string;
  name: string;
  surface_area_km2: number;
  acquisition_date: string;
}

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

export interface TimeseriesPoint {
  date: string;
  pct_filled: number;
  level_m: number | null;
  live_storage_bcm: number | null;
  normal_storage_pct: number | null;
}

export interface ForecastPoint {
  horizon_date: string;
  predicted_pct_filled: number;
  interval_low: number;
  interval_high: number;
}

export interface Forecast {
  reservoir_id: string;
  horizon: number;
  points: ForecastPoint[];
}

export interface FleetRisk {
  reservoir_id: string;
  risk_level: RiskLevel;
  release_probability: number;
  estimated_lead_time_days: number | null;
  run_timestamp: string;
}

/** Properties on `/geojson/reservoirs` marker features. */
export interface ReservoirMarkerProperties {
  reservoir_id: string;
  name: string;
  frl_m: number;
  risk_level: RiskLevel | null;
  release_probability: number | null;
}

export interface ReservoirFeature {
  type: "Feature";
  geometry: { type: "Point"; coordinates: [number, number] } | null;
  properties: ReservoirMarkerProperties;
}

export interface FeatureCollection {
  type: "FeatureCollection";
  features: ReservoirFeature[];
}

export const RISK_COLOR: Record<RiskLevel, string> = {
  Low: "#2c7fb8",
  Watch: "#fec44f",
  Warning: "#fe9929",
  Imminent: "#d7301f",
};

// Dark text on the light tiers (Watch/Warning): white fails WCAG contrast there.
export const RISK_TEXT_COLOR: Record<RiskLevel, string> = {
  Low: "#ffffff",
  Watch: "#1a1a1a",
  Warning: "#1a1a1a",
  Imminent: "#ffffff",
};

/** Neutral grey for unknown risk — must never reuse the calm Low blue. */
export const UNKNOWN_RISK_COLOR = "#94a3b8";
export const UNKNOWN_RISK_TEXT_COLOR = "#1a1a1a";
