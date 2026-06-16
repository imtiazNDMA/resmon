import { useEffect, useMemo, useState } from "react";

import { api } from "./api";
import { ForecastChart } from "./components/ForecastChart";
import { ReservoirMap } from "./components/ReservoirMap";
import { TrendChart } from "./components/TrendChart";
import {
  RISK_COLOR,
  type FeatureCollection,
  type Forecast,
  type Reservoir,
  type RiskLevel,
  type Status,
  type TimeseriesPoint,
} from "./types";

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
  const [geojson, setGeojson] = useState<FeatureCollection | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [series, setSeries] = useState<TimeseriesPoint[]>([]);
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.reservoirs(), api.geojson()])
      .then(([rs, gj]) => {
        setReservoirs(rs);
        setGeojson(gj);
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

  return (
    <div className="app">
      <header>
        <h1>Reservoir Monitoring &amp; Analytics</h1>
        <p className="muted">
          SAR-derived storage &amp; release-risk early warning · weather-immune ·{" "}
          {status?.last_acquisition_date
            ? `last acquisition ${status.last_acquisition_date}`
            : "awaiting first SAR acquisition"}
        </p>
      </header>

      {error && <div className="error">⚠ {error}</div>}

      <div className="layout">
        <section className="map-pane">
          <ReservoirMap features={geojson} onSelect={setSelected} />
        </section>

        <section className="detail-pane">
          <div className="reservoir-tabs">
            {reservoirs.map((r) => (
              <button
                key={r.reservoir_id}
                className={r.reservoir_id === selected ? "active" : ""}
                onClick={() => setSelected(r.reservoir_id)}
              >
                {r.name}
              </button>
            ))}
          </div>

          {selectedReservoir && (
            <>
              <div className="detail-head">
                <h2>{selectedReservoir.name}</h2>
                <RiskBadge level={status?.risk_level ?? null} />
              </div>

              <div className="kpis">
                <Kpi label="fill" value={status ? `${status.pct_filled.toFixed(1)}%` : "…"} />
                <Kpi
                  label="level vs FRL"
                  value={
                    status?.level_m != null
                      ? `${status.level_m.toFixed(1)} / ${selectedReservoir.frl_m.toFixed(0)} m`
                      : "…"
                  }
                />
                <Kpi
                  label="storage"
                  value={
                    status?.live_storage_bcm != null
                      ? `${status.live_storage_bcm.toFixed(2)} BCM`
                      : "…"
                  }
                />
                <Kpi
                  label="release prob · lead"
                  value={
                    status?.release_probability != null
                      ? `${(status.release_probability * 100).toFixed(0)}% · ${
                          status.estimated_lead_time_days ?? "—"
                        }d`
                      : "…"
                  }
                />
              </div>

              <h3>Storage trend (vs seasonal normal)</h3>
              <TrendChart points={series} />

              <h3>1–14 day forecast (conformal interval)</h3>
              <ForecastChart forecast={forecast} />
            </>
          )}
        </section>
      </div>
    </div>
  );
}
