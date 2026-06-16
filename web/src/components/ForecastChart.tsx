import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { Forecast } from "../types";

export function ForecastChart({ forecast }: { forecast: Forecast | null }) {
  if (!forecast || forecast.points.length === 0) {
    return <p className="muted">No forecast available.</p>;
  }
  const data = forecast.points.map((p) => ({
    date: p.horizon_date,
    predicted: Number(p.predicted_pct_filled),
    low: Number(p.interval_low),
    high: Number(p.interval_high),
    band: [Number(p.interval_low), Number(p.interval_high)],
  }));
  return (
    <ResponsiveContainer width="100%" height={220}>
      <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -16 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
        <XAxis dataKey="date" tick={{ fontSize: 10 }} />
        <YAxis domain={[0, 110]} tick={{ fontSize: 10 }} unit="%" />
        <Tooltip />
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
