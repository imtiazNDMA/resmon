import type { FeatureCollection, FleetRisk, Forecast, Reservoir, Status, TimeseriesPoint } from "./types";

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
};
