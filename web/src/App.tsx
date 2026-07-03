import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, isAbortError } from "./api";
import { ForecastChart } from "./components/ForecastChart";
import { ReservoirMap } from "./components/ReservoirMap";
import { TrendChart } from "./components/TrendChart";
import {
  RISK_COLOR,
  RISK_TEXT_COLOR,
  UNKNOWN_RISK_COLOR,
  UNKNOWN_RISK_TEXT_COLOR,
  type FeatureCollection,
  type FleetRisk,
  type Forecast,
  type GeoFC,
  type Reservoir,
  type RiskLevel,
  type Status,
  type TimeseriesPoint,
  type WaterExtentProperties,
} from "./types";

const REFRESH_INTERVAL_MS = 90_000;

type SourceKey = "reservoirs" | "markers" | "aoi" | "catchment" | "water" | "fleet" | "detail";

const SOURCE_LABEL: Record<SourceKey, string> = {
  reservoirs: "Reservoir list",
  markers: "Risk markers",
  aoi: "AOI overlay",
  catchment: "Catchment overlay",
  water: "Water-extent overlay",
  fleet: "Fleet risk",
  detail: "Reservoir detail",
};

// Coerce defensively: Postgres `numeric` may arrive as a string ("512.000").
const fx = (v: number | string | null | undefined, digits = 1): string =>
  v == null || Number.isNaN(Number(v)) ? "—" : Number(v).toFixed(digits);

function RiskBadge({ level }: { level: RiskLevel | null }) {
  // Unknown is grey, never the calm Low blue.
  const background = level ? RISK_COLOR[level] : UNKNOWN_RISK_COLOR;
  const color = level ? RISK_TEXT_COLOR[level] : UNKNOWN_RISK_TEXT_COLOR;
  return (
    <span className="badge" style={{ background, color }}>
      {level ?? "Unknown"}
    </span>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="kpi">
      <div className="kpi-value">{value}</div>
      <div className="kpi-label">{label}</div>
    </div>
  );
}

export default function App() {
  const [reservoirs, setReservoirs] = useState<Reservoir[]>([]);
  const [markers, setMarkers] = useState<FeatureCollection | null>(null);
  const [aoi, setAoi] = useState<GeoFC | null>(null);
  const [catchment, setCatchment] = useState<GeoFC | null>(null);
  const [water, setWater] = useState<GeoFC<WaterExtentProperties> | null>(null);
  const [fleet, setFleet] = useState<FleetRisk[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [series, setSeries] = useState<TimeseriesPoint[]>([]);
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [errors, setErrors] = useState<Partial<Record<SourceKey, string>>>({});
  const [refreshTick, setRefreshTick] = useState(0);

  const clearError = useCallback((key: SourceKey) => {
    setErrors((prev) => {
      if (prev[key] == null) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }, []);

  const reportError = useCallback((key: SourceKey, e: unknown) => {
    if (isAbortError(e)) return;
    setErrors((prev) => ({ ...prev, [key]: e instanceof Error ? e.message : String(e) }));
  }, []);

  const staticLoaders = useMemo(
    () => ({
      reservoirs: async (signal?: AbortSignal) => {
        const rs = await api.reservoirs(signal);
        setReservoirs(rs);
        setSelected((cur) => cur ?? rs[0]?.reservoir_id ?? null);
      },
      markers: async (signal?: AbortSignal) => setMarkers(await api.geojson(signal)),
      aoi: async (signal?: AbortSignal) => setAoi(await api.aoi(signal)),
      catchment: async (signal?: AbortSignal) => setCatchment(await api.catchment(signal)),
      water: async (signal?: AbortSignal) => setWater(await api.waterExtent(signal)),
      fleet: async (signal?: AbortSignal) => setFleet(await api.fleetRisk(signal)),
    }),
    [],
  );

  const loadSource = useCallback(
    async (key: Exclude<SourceKey, "detail">, signal?: AbortSignal) => {
      try {
        await staticLoaders[key](signal);
        clearError(key);
      } catch (e) {
        reportError(key, e);
      }
    },
    [staticLoaders, clearError, reportError],
  );

  // Initial load: each source settles independently — one flaky GEE overlay must
  // never blank the risk markers/KPIs.
  useEffect(() => {
    const ctrl = new AbortController();
    const keys = Object.keys(staticLoaders) as Exclude<SourceKey, "detail">[];
    void Promise.allSettled(keys.map((k) => loadSource(k, ctrl.signal)));
    return () => ctrl.abort();
  }, [staticLoaders, loadSource]);

  // Poll every 90 s + refetch on window focus (dynamic sources only; the
  // geometry overlays are static).
  useEffect(() => {
    const bump = () => setRefreshTick((t) => t + 1);
    const id = window.setInterval(bump, REFRESH_INTERVAL_MS);
    window.addEventListener("focus", bump);
    return () => {
      window.clearInterval(id);
      window.removeEventListener("focus", bump);
    };
  }, []);

  useEffect(() => {
    if (refreshTick === 0) return; // initial load already fetched fleet risk
    const ctrl = new AbortController();
    void loadSource("fleet", ctrl.signal);
    return () => ctrl.abort();
  }, [refreshTick, loadSource]);

  // Tracks which reservoir the detail pane currently shows, so polling refreshes
  // in place while a genuine switch clears stale data first.
  const detailIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (!selected) return;
    if (detailIdRef.current !== selected) {
      // Switching reservoirs: drop the previous reservoir's status AND
      // series/forecast immediately so they never render under the new header.
      detailIdRef.current = selected;
      setStatus(null);
      setSeries([]);
      setForecast(null);
    }
    const ctrl = new AbortController();
    const { signal } = ctrl;
    // Aborting rejects in-flight fetches, but a fetch that already resolved can
    // still have its .then queued — the signal check closes that race window.
    const guard =
      <T,>(apply: (v: T) => void) =>
      (v: T) => {
        if (!signal.aborted) apply(v);
      };
    void Promise.allSettled([
      api.status(selected, signal).then(guard(setStatus)),
      api.timeseries(selected, 200, signal).then(guard(setSeries)),
      api.forecast(selected, signal).then(guard(setForecast)),
    ]).then((results) => {
      const failure = results.find(
        (r): r is PromiseRejectedResult => r.status === "rejected" && !isAbortError(r.reason),
      );
      if (failure) reportError("detail", failure.reason);
      else if (!signal.aborted) clearError("detail");
    });
    return () => ctrl.abort();
  }, [selected, refreshTick, reportError, clearError]);

  const retrySource = useCallback(
    (key: SourceKey) => {
      if (key === "detail") setRefreshTick((t) => t + 1);
      else void loadSource(key);
    },
    [loadSource],
  );

  const errorEntries = useMemo(
    () => Object.entries(errors) as [SourceKey, string][],
    [errors],
  );

  const selectedReservoir = useMemo(
    () => reservoirs.find((r) => r.reservoir_id === selected) ?? null,
    [reservoirs, selected],
  );

  const waterInfo = useMemo<WaterExtentProperties | undefined>(
    () => water?.features.find((x) => x.properties.reservoir_id === selected)?.properties,
    [water, selected],
  );

  return (
    <div className="gis">
      <header className="topbar">
        <div className="brand">
          <span className="logo">◉</span>
          <div>
            <div className="title">Reservoir Monitoring &amp; Analytics</div>
            <div className="subtitle">SAR-derived storage · release-risk early warning</div>
          </div>
        </div>
        <div className="fleet-chips">
          {fleet.map((f) => (
            <button
              key={f.reservoir_id}
              className={`chip ${f.reservoir_id === selected ? "active" : ""}`}
              style={{ borderColor: RISK_COLOR[f.risk_level] }}
              onClick={() => setSelected(f.reservoir_id)}
            >
              <span className="chip-dot" style={{ background: RISK_COLOR[f.risk_level] }} />
              {reservoirs.find((r) => r.reservoir_id === f.reservoir_id)?.name ?? f.reservoir_id}
              <span className="chip-risk">{f.risk_level}</span>
            </button>
          ))}
        </div>
      </header>

      {errorEntries.length > 0 && (
        <div className="error-stack">
          {errorEntries.map(([key, msg]) => (
            <div key={key} className="error">
              <span>
                ⚠ {SOURCE_LABEL[key]}: {msg}
              </span>
              <button className="retry" onClick={() => retrySource(key)}>
                Retry
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="gis-body">
        <section className="map-pane">
          <ReservoirMap
            markers={markers}
            aoi={aoi}
            catchment={catchment}
            water={water}
            selectedId={selected}
            onSelect={setSelected}
          />
        </section>

        <aside className="side-pane">
          {selectedReservoir && (
            <>
              <div className="detail-head">
                <div>
                  <h2>{selectedReservoir.name}</h2>
                  <div className="muted">{selectedReservoir.basin} basin</div>
                </div>
                <RiskBadge level={status?.risk_level ?? null} />
              </div>

              {status?.stale && (
                <div className="stale-banner">
                  ⏳{" "}
                  {status.data_age_days != null
                    ? `Data ${status.data_age_days}d old`
                    : "Data age unknown"}{" "}
                  · serving last-known forecast-based risk
                </div>
              )}

              <div className="kpis">
                <Kpi label="fill" value={status ? `${fx(status.pct_filled, 1)}%` : "…"} />
                <Kpi
                  label="level / FRL"
                  value={
                    status?.level_m != null
                      ? `${fx(status.level_m, 0)} / ${fx(selectedReservoir.frl_m, 0)} m`
                      : "…"
                  }
                />
                <Kpi
                  label="storage"
                  value={status?.live_storage_bcm != null ? `${fx(status.live_storage_bcm, 2)} BCM` : "…"}
                />
                <Kpi
                  label="release prob · lead"
                  value={
                    status?.release_probability != null
                      ? `${fx(Number(status.release_probability) * 100, 0)}% · ${
                          status.estimated_lead_time_days ?? "—"
                        }d`
                      : "…"
                  }
                />
              </div>

              {waterInfo?.surface_area_km2 != null && (
                <div className="sar-line">
                  🛰 Sentinel-1 water extent: <b>{fx(waterInfo.surface_area_km2, 1)} km²</b>
                  {waterInfo.acquisition_date ? ` · ${waterInfo.acquisition_date}` : ""}
                </div>
              )}

              <h3>Storage trend (vs seasonal normal)</h3>
              <TrendChart points={series} />

              <h3>1–14 day forecast (conformal interval)</h3>
              <ForecastChart forecast={forecast} />

              <p className="footnote">
                Accuracy is a historical backtest. AOI (JRC GSW), catchment (HydroBASINS) and
                water extent (Sentinel-1) are live from Google Earth Engine.
              </p>
            </>
          )}
        </aside>
      </div>
    </div>
  );
}
