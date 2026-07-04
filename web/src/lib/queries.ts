import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "./api";

export const useMarkers = () =>
  useQuery({ queryKey: ["markers"], queryFn: ({ signal }) => api.markers(signal) });

export const useAoi = () =>
  useQuery({ queryKey: ["aoi"], queryFn: ({ signal }) => api.aoi(signal), staleTime: Infinity });

export const useCatchment = () =>
  useQuery({
    queryKey: ["catchment"],
    queryFn: ({ signal }) => api.catchment(signal),
    staleTime: Infinity, // catchment geometry is static, same contract as useAoi
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
  });

export const useAcquisitions = (rid: string | null) =>
  useQuery({
    queryKey: ["acquisitions", rid],
    queryFn: ({ signal }) => api.acquisitions(rid!, signal),
    enabled: rid !== null,
    staleTime: 10 * 60_000,
  });

export const useSarTile = (rid: string | null, date: string | null) =>
  useQuery({
    queryKey: ["sarTile", rid, date],
    queryFn: ({ signal }) => api.sarTile(rid!, date!, signal),
    enabled: rid !== null && date !== null,
    staleTime: 3 * 60 * 60_000, // matches the server-side mint TTL
    retry: (count, err) => !(err instanceof ApiError && err.status === 503) && count < 2,
  });

export const useRainfall = (rid: string | null) =>
  useQuery({
    queryKey: ["rainfall", rid],
    queryFn: ({ signal }) => api.rainfall(rid!, signal),
    enabled: rid !== null,
  });
