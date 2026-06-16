import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { TimeseriesPoint } from "../types";

export function TrendChart({ points }: { points: TimeseriesPoint[] }) {
  if (points.length === 0) return <p className="muted">No history.</p>;
  const data = points.map((p) => ({
    date: p.date,
    fill: Number(p.pct_filled),
    normal: p.normal_storage_pct == null ? null : Number(p.normal_storage_pct),
  }));
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -16 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
        <XAxis dataKey="date" tick={{ fontSize: 10 }} minTickGap={40} />
        <YAxis domain={[0, 110]} tick={{ fontSize: 10 }} unit="%" />
        <Tooltip />
        <Legend />
        <Line type="monotone" dataKey="fill" stroke="#2c7fb8" dot={false} name="fill %" />
        <Line
          type="monotone"
          dataKey="normal"
          stroke="#999"
          strokeDasharray="4 4"
          dot={false}
          name="seasonal normal"
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
