import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { Forecast } from "../types";

// The band arrives as [low, high]; render "45.2–55.3%" instead of a raw array.
const pct = (v: unknown): string =>
  Array.isArray(v)
    ? `${Number(v[0]).toFixed(1)}–${Number(v[1]).toFixed(1)}%`
    : `${Number(v).toFixed(1)}%`;

export function ForecastChart({ forecast }: { forecast: Forecast | null }) {
  if (!forecast || forecast.points.length === 0) {
    return <p className="muted">No forecast available.</p>;
  }
  const data = forecast.points.map((p) => ({
    date: p.horizon_date,
    predicted: Number(p.predicted_pct_filled),
    band: [Number(p.interval_low), Number(p.interval_high)],
  }));
  return (
    <ResponsiveContainer width="100%" height={220}>
      <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -16 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
        <XAxis dataKey="date" tick={{ fontSize: 10 }} />
        {/* Never clip the overtopping scenario: grow the axis past 110% when needed. */}
        <YAxis
          domain={[0, (dataMax: number) => Math.max(110, Math.ceil(dataMax + 5))]}
          tick={{ fontSize: 10 }}
          unit="%"
        />
        <Tooltip formatter={(value, name) => [pct(value), name]} />
        <ReferenceLine
          y={100}
          stroke="#d7301f"
          strokeDasharray="4 4"
          label={{ value: "FRL", position: "insideTopRight", fontSize: 10, fill: "#d7301f" }}
        />
        <Area
          type="monotone"
          dataKey="band"
          stroke="none"
          fill="#2c7fb8"
          fillOpacity={0.15}
          name="conformal interval"
        />
        <Line type="monotone" dataKey="predicted" stroke="#2c7fb8" dot={false} name="forecast fill %" />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
