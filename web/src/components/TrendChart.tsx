import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { TimeseriesPoint } from "../types";

const pct = (v: unknown): string => (v == null ? "—" : `${Number(v).toFixed(1)}%`);

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
