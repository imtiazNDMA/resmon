import { useEffect, useMemo, useState } from "react";

import { api } from "./api";
import { ForecastChart } from "./components/ForecastChart";
import { ReservoirMap } from "./components/ReservoirMap";
import { TrendChart } from "./components/TrendChart";
import {
  RISK_COLOR,
  type FeatureCollection,
  type FleetRisk,
  type Forecast,
  type GeoFC,
  type Reservoir,
  type RiskLevel,
  type Status,
  type TimeseriesPoint,
} from "./types";

// Coerce defensively: Postgres `numeric` may arrive as a string ("512.000").
const fx = (v: number | string | null | undefined, digits = 1): string =>
  v == null || Number.isNaN(Number(v)) ? "—" : Number(v).toFixed(digits);

function RiskBadge({ level }: { level: RiskLevel | null }) {
  const lvl = level ?? "Low";
  return (
    <span className="badge" style={{ background: RISK_COLOR[lvl] }}>
      {level ?? "—"}
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
  const [water, setWater] = useState<GeoFC | null>(null);
  const [fleet, setFleet] = useState<FleetRisk[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [series, setSeries] = useState<TimeseriesPoint[]>([]);
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api.reservoirs(),
      api.geojson(),
      api.aoi(),
      api.catchment(),
      api.waterExtent(),
      api.fleetRisk(),
    ])
      .then(([rs, gj, a, c, w, fr]) => {
        setReservoirs(rs);
        setMarkers(gj);
        setAoi(a);
        setCatchment(c);
        setWater(w);
        setFleet(fr);
        if (rs.length > 0) setSelected(rs[0].reservoir_id);
      })
      .catch((e: unknown) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!selected) return;
    setStatus(null);
    Promise.all([api.status(selected), api.timeseries(selected, 200), api.forecast(selected)])
      .then(([st, ts, fc]) => {
        setStatus(st);
        setSeries(ts);
        setForecast(fc);
      })
      .catch((e: unknown) => setError(String(e)));
  }, [selected]);

  const selectedReservoir = useMemo(
    () => reservoirs.find((r) => r.reservoir_id === selected) ?? null,
    [reservoirs, selected],
  );

  const waterInfo = useMemo(() => {
    const f = water?.features.find((x) => x.properties?.reservoir_id === selected);
    return f?.properties as
      | { surface_area_km2?: number; acquisition_date?: string }
      | undefined;
  }, [water, selected]);

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

      {error && <div className="error">⚠ {error}</div>}

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
                  ⏳ Data {status.data_age_days}d old · serving last-known forecast-based risk
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
