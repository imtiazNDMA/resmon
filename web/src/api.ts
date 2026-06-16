import type {
  FeatureCollection,
  FleetRisk,
  Forecast,
  GeoFC,
  Reservoir,
  Status,
  TimeseriesPoint,
} from "./types";

const BASE = "/api";

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return (await res.json()) as T;
}

export const api = {
  reservoirs: () => getJson<Reservoir[]>("/reservoirs"),
  status: (id: string) => getJson<Status>(`/reservoirs/${id}/status`),
  timeseries: (id: string, limit = 200) =>
    getJson<TimeseriesPoint[]>(`/reservoirs/${id}/timeseries?limit=${limit}`),
  forecast: (id: string) => getJson<Forecast>(`/reservoirs/${id}/forecast`),
  fleetRisk: () => getJson<FleetRisk[]>("/release-risk"),
  geojson: () => getJson<FeatureCollection>("/geojson/reservoirs"),
  aoi: () => getJson<GeoFC>("/geojson/aoi"),
  catchment: () => getJson<GeoFC>("/geojson/catchment"),
  waterExtent: () => getJson<GeoFC>("/geojson/water-extent"),
};
