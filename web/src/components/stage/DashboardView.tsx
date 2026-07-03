import { useEffect, useRef } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { panelsIn } from "../../lib/motion";
import { useAcquisitions, useRainfall, useStatus } from "../../lib/queries";
import type { ReservoirId } from "../../lib/store";

const IDS: ReservoirId[] = ["gobind_sagar", "pong", "thein"];
const NAMES = { gobind_sagar: "Gobind Sagar", pong: "Pong", thein: "Thein" } as const;
const COLORS = { gobind_sagar: "#59b7ff", pong: "#7ee2a8", thein: "#e8b45a" } as const;

export default function DashboardView() {
  const rootRef = useRef<HTMLDivElement>(null);
  const gob = useAcquisitions("gobind_sagar");
  const pon = useAcquisitions("pong");
  const the = useAcquisitions("thein");
  const statuses = {
    gobind_sagar: useStatus("gobind_sagar"),
    pong: useStatus("pong"),
    thein: useStatus("thein"),
  };
  const rain = useRainfall("gobind_sagar");

  useEffect(() => {
    if (rootRef.current) panelsIn(rootRef.current);
  }, []);

  // merge the three series onto one date axis for the fleet chart
  const byDate = new Map<string, Record<string, number | string>>();
  for (const [id, q] of [
    ["gobind_sagar", gob],
    ["pong", pon],
    ["thein", the],
  ] as const) {
    for (const a of q.data ?? []) {
      const row = byDate.get(a.date) ?? { date: a.date };
      row[id] = a.area_km2;
      byDate.set(a.date, row);
    }
  }
  const fleet = [...byDate.values()].sort((a, b) =>
    String(a.date).localeCompare(String(b.date)),
  );

  return (
    <div className="dashview" ref={rootRef}>
      <div className="panel panel-wide">
        <div className="panel-title">SURFACE AREA — SAR, ALL RESERVOIRS</div>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={fleet}>
            <CartesianGrid stroke="var(--line)" strokeDasharray="3 3" />
            <XAxis dataKey="date" stroke="var(--muted)" fontSize={10} minTickGap={60} />
            <YAxis stroke="var(--muted)" fontSize={10} unit=" km²" />
            <Tooltip
              contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)" }}
            />
            {IDS.map((id) => (
              <Line
                key={id}
                dataKey={id}
                name={NAMES[id]}
                stroke={COLORS[id]}
                dot={false}
                strokeWidth={1.5}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      {IDS.map((id) => {
        const s = statuses[id].data;
        return (
          <div className="panel" key={id}>
            <div className="panel-title">{NAMES[id].toUpperCase()}</div>
            <div className="kpi-big">
              {s ? Number(s.pct_filled).toFixed(1) : "—"}
              <small>% fill</small>
            </div>
            <div className="kpi-sub">
              level {s?.level_m != null ? Number(s.level_m).toFixed(1) : "—"} m ·{" "}
              {s?.live_storage_bcm != null ? Number(s.live_storage_bcm).toFixed(2) : "—"} BCM
            </div>
          </div>
        );
      })}
      <div className="panel panel-wide">
        <div className="panel-title">CATCHMENT RAINFALL — 90 D</div>
        {rain.data && rain.data.length > 0 ? (
          <ResponsiveContainer width="100%" height={120}>
            <LineChart data={rain.data}>
              <XAxis dataKey="date" stroke="var(--muted)" fontSize={10} minTickGap={60} />
              <YAxis stroke="var(--muted)" fontSize={10} unit=" mm" />
              <Line dataKey="precip_mm" stroke="var(--water)" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div className="empty-state">awaiting live forcing ingest — no rainfall data yet</div>
        )}
      </div>
    </div>
  );
}
