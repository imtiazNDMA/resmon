import type {
  FeatureCollection,
  FleetRisk,
  Forecast,
  GeoFC,
  Reservoir,
  Status,
  TimeseriesPoint,
  WaterExtentProperties,
} from "./types";

const BASE = "/api";

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { signal });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return (await res.json()) as T;
}

/** True when a fetch was cancelled via AbortController — callers must ignore these. */
export function isAbortError(e: unknown): boolean {
  return e instanceof DOMException && e.name === "AbortError";
}

export const api = {
  reservoirs: (signal?: AbortSignal) => getJson<Reservoir[]>("/reservoirs", signal),
  status: (id: string, signal?: AbortSignal) =>
    getJson<Status>(`/reservoirs/${id}/status`, signal),
  timeseries: (id: string, limit = 200, signal?: AbortSignal) =>
    getJson<TimeseriesPoint[]>(`/reservoirs/${id}/timeseries?limit=${limit}`, signal),
  forecast: (id: string, signal?: AbortSignal) =>
    getJson<Forecast>(`/reservoirs/${id}/forecast`, signal),
  fleetRisk: (signal?: AbortSignal) => getJson<FleetRisk[]>("/release-risk", signal),
  geojson: (signal?: AbortSignal) => getJson<FeatureCollection>("/geojson/reservoirs", signal),
  aoi: (signal?: AbortSignal) => getJson<GeoFC>("/geojson/aoi", signal),
  catchment: (signal?: AbortSignal) => getJson<GeoFC>("/geojson/catchment", signal),
  waterExtent: (signal?: AbortSignal) =>
    getJson<GeoFC<WaterExtentProperties>>("/geojson/water-extent", signal),
};
