import type {
  Acquisition,
  AoiProperties,
  CatchmentProperties,
  DistrictBoundaryProperties,
  FlowEdgeProperties,
  FlowlineProperties,
  GeoFC,
  HydrologicLayerProvenance,
  MetForcing,
  PmdMonsoonProperties,
  PmdStationObservationProperties,
  PmdWarningProperties,
  RainfallPoint,
  Reservoir,
  ReservoirMarkerProperties,
  SarAssetManifestEntry,
  SarTile,
  Status,
  SubBasinProperties,
  WaterExtentProperties,
} from "../types";
import type { SarCompositeId } from "./sarComposites";

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
  sarTile: (rid: string, date: string, composite: SarCompositeId, s?: AbortSignal) =>
    getJson<SarTile>(`/reservoirs/${rid}/sar-tiles?date=${date}&composite=${composite}`, s),
  sarAssets: (rid: string, s?: AbortSignal) =>
    getJson<SarAssetManifestEntry[]>(`/reservoirs/${rid}/sar-assets`, s),
  rainfall: (rid: string, s?: AbortSignal) =>
    getJson<RainfallPoint[]>(`/reservoirs/${rid}/rainfall?window=90`, s),
  metForcings: (rid: string, s?: AbortSignal) =>
    getJson<MetForcing>(`/reservoirs/${rid}/met-forcings`, s),
  markers: (s?: AbortSignal) =>
    getJson<GeoFC<ReservoirMarkerProperties>>("/geojson/reservoirs", s),
  aoi: (s?: AbortSignal) => getJson<GeoFC<AoiProperties>>("/geojson/aoi", s),
  catchment: (s?: AbortSignal) => getJson<GeoFC<CatchmentProperties>>("/geojson/catchment", s),
  subbasins: (s?: AbortSignal) => getJson<GeoFC<SubBasinProperties>>("/geojson/subbasins", s),
  flowEdges: (s?: AbortSignal) => getJson<GeoFC<FlowEdgeProperties>>("/geojson/flow-edges", s),
  flowlines: (rid: string, minOrder = 1, s?: AbortSignal) =>
    getJson<GeoFC<FlowlineProperties>>(
      `/geojson/hydrologic/flowlines?reservoir_id=${rid}&min_order=${minOrder}`,
      s,
    ),
  hydrologicProvenance: (rid: string, s?: AbortSignal) =>
    getJson<HydrologicLayerProvenance[]>(
      `/hydrologic/layers/provenance?reservoir_id=${rid}`,
      s,
    ),
  districts: (s?: AbortSignal) =>
    getJson<GeoFC<DistrictBoundaryProperties>>("/geojson/districts", s),
  waterExtent: (s?: AbortSignal) =>
    getJson<GeoFC<WaterExtentProperties>>("/geojson/water-extent", s),
  pmdStations: (s?: AbortSignal) =>
    getJson<GeoFC<PmdStationObservationProperties>>("/weather/pmd/monitor/stations", s),
  pmdWarnings: (s?: AbortSignal) =>
    getJson<GeoFC<PmdWarningProperties>>("/weather/pmd/monitor/warnings", s),
  pmdMonsoon: (s?: AbortSignal) =>
    getJson<GeoFC<PmdMonsoonProperties>>("/weather/pmd/monitor/monsoon", s),
};
