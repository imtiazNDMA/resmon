import type {
  Acquisition,
  AoiProperties,
  CatchmentProperties,
  GeoFC,
  RainfallPoint,
  Reservoir,
  ReservoirMarkerProperties,
  SarTile,
  Status,
  WaterExtentProperties,
} from "../types";

const BASE = "/api";

export class ApiError extends Error {
  constructor(
    public status: number,
    public url: string,
  ) {
    super(`${url} -> ${status}`);
  }
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { signal });
  if (!res.ok) throw new ApiError(res.status, path);
  return (await res.json()) as T;
}

export const api = {
  reservoirs: (s?: AbortSignal) => getJson<Reservoir[]>("/reservoirs", s),
  status: (rid: string, s?: AbortSignal) => getJson<Status>(`/reservoirs/${rid}/status`, s),
  acquisitions: (rid: string, s?: AbortSignal) =>
    getJson<Acquisition[]>(`/reservoirs/${rid}/acquisitions`, s),
  sarTile: (rid: string, date: string, s?: AbortSignal) =>
    getJson<SarTile>(`/reservoirs/${rid}/sar-tiles?date=${date}`, s),
  rainfall: (rid: string, s?: AbortSignal) =>
    getJson<RainfallPoint[]>(`/reservoirs/${rid}/rainfall?window=90`, s),
  markers: (s?: AbortSignal) =>
    getJson<GeoFC<ReservoirMarkerProperties>>("/geojson/reservoirs", s),
  aoi: (s?: AbortSignal) => getJson<GeoFC<AoiProperties>>("/geojson/aoi", s),
  catchment: (s?: AbortSignal) => getJson<GeoFC<CatchmentProperties>>("/geojson/catchment", s),
  waterExtent: (s?: AbortSignal) =>
    getJson<GeoFC<WaterExtentProperties>>("/geojson/water-extent", s),
};
