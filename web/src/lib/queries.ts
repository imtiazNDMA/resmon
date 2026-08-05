import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "./api";
import type { SarCompositeId } from "./sarComposites";

export const useMarkers = () =>
  useQuery({
    queryKey: ["markers"],
    queryFn: ({ signal }) => api.markers(signal),
    staleTime: 10 * 60_000,
  });

export const useReservoirs = () =>
  useQuery({
    queryKey: ["reservoirs"],
    queryFn: ({ signal }) => api.reservoirs(signal),
    staleTime: 10 * 60_000,
  });

export const useAoi = () =>
  useQuery({ queryKey: ["aoi"], queryFn: ({ signal }) => api.aoi(signal), staleTime: Infinity });

export const useCatchment = () =>
  useQuery({
    queryKey: ["catchment"],
    queryFn: ({ signal }) => api.catchment(signal),
    staleTime: Infinity, // catchment geometry is static, same contract as useAoi
  });

export const useSubBasins = () =>
  useQuery({
    queryKey: ["subbasins"],
    queryFn: ({ signal }) => api.subbasins(signal),
    staleTime: Infinity, // basin geometry is static, same contract as useCatchment
  });

export const useFlowEdges = () =>
  useQuery({
    queryKey: ["flowEdges"],
    queryFn: ({ signal }) => api.flowEdges(signal),
    staleTime: Infinity, // topology-derived geometry changes only when catchments refresh
  });

export const useFlowlines = (rid: string | null, minOrder = 1) =>
  useQuery({
    queryKey: ["flowlines", rid, minOrder],
    queryFn: ({ signal }) => api.flowlines(rid!, minOrder, signal),
    enabled: rid !== null,
    staleTime: Infinity, // drainage vectors are static map cartography
  });

export const useHydrologicProvenance = (rid: string | null) =>
  useQuery({
    queryKey: ["hydrologicProvenance", rid],
    queryFn: ({ signal }) => api.hydrologicProvenance(rid!, signal),
    enabled: rid !== null,
    staleTime: Infinity,
  });

export const useDistricts = () =>
  useQuery({
    queryKey: ["districts"],
    queryFn: ({ signal }) => api.districts(signal),
    staleTime: Infinity,
  });

export const useWaterExtent = () =>
  useQuery({
    queryKey: ["waterExtent"],
    queryFn: ({ signal }) => api.waterExtent(signal),
    staleTime: 10 * 60_000, // a new mask lands at most per-scene; matches acquisitions
  });

export const useStatus = (rid: string | null) =>
  useQuery({
    queryKey: ["status", rid],
    queryFn: ({ signal }) => api.status(rid!, signal),
    enabled: rid !== null,
    refetchInterval: 90_000,
    staleTime: 60_000,
  });

export const useAcquisitions = (rid: string | null) =>
  useQuery({
    queryKey: ["acquisitions", rid],
    queryFn: ({ signal }) => api.acquisitions(rid!, signal),
    enabled: rid !== null,
    staleTime: 10 * 60_000,
  });

export const sarTileQuery = (rid: string, date: string, composite: SarCompositeId) => ({
  queryKey: ["sarTile", rid, date, composite],
  queryFn: ({ signal }: { signal: AbortSignal }) => api.sarTile(rid, date, composite, signal),
  staleTime: 3 * 60 * 60_000, // matches the server-side mint TTL
  retry: (count: number, err: Error) => !(err instanceof ApiError && err.status === 503) && count < 2,
});

export const useSarTile = (rid: string | null, date: string | null, composite: SarCompositeId) =>
  useQuery({
    ...sarTileQuery(rid ?? "", date ?? "", composite),
    enabled: rid !== null && date !== null,
  });

export const useRainfall = (rid: string | null) =>
  useQuery({
    queryKey: ["rainfall", rid],
    queryFn: ({ signal }) => api.rainfall(rid!, signal),
    enabled: rid !== null,
    staleTime: 10 * 60_000,
  });

export const useMetForcings = (rid: string | null) =>
  useQuery({
    queryKey: ["metForcings", rid],
    queryFn: ({ signal }) => api.metForcings(rid!, signal),
    enabled: rid !== null,
    staleTime: 10 * 60_000,
  });

export const usePmdStations = (enabled = true) =>
  useQuery({
    queryKey: ["pmdStations"],
    queryFn: ({ signal }) => api.pmdStations(signal),
    enabled,
    staleTime: 5 * 60_000,
    retry: (count, err) => !(err instanceof ApiError && err.status === 503) && count < 2,
  });

export const usePmdWarnings = (enabled = true) =>
  useQuery({
    queryKey: ["pmdWarnings"],
    queryFn: ({ signal }) => api.pmdWarnings(signal),
    enabled,
    staleTime: 2 * 60_000,
    retry: (count, err) => !(err instanceof ApiError && err.status === 503) && count < 2,
  });

export const usePmdMonsoon = (enabled = true) =>
  useQuery({
    queryKey: ["pmdMonsoon"],
    queryFn: ({ signal }) => api.pmdMonsoon(signal),
    enabled,
    staleTime: 5 * 60_000,
    retry: (count, err) => !(err instanceof ApiError && err.status === 503) && count < 2,
  });

export const usePmdLightning = (hours: number, enabled = true) =>
  useQuery({
    queryKey: ["pmdLightning", hours],
    queryFn: ({ signal }) => api.pmdLightning(hours, signal),
    enabled,
    staleTime: 3 * 60_000,
    retry: (count, err) => !(err instanceof ApiError && err.status === 503) && count < 2,
  });
