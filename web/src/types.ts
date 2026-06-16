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

export interface ReservoirFeature {
  type: "Feature";
  geometry: { type: "Point"; coordinates: [number, number] } | null;
  properties: {
    reservoir_id: string;
    name: string;
    frl_m: number;
    risk_level: RiskLevel | null;
    release_probability: number | null;
  };
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
