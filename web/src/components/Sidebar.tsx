import { useAppStore } from "../lib/store";
import { useAcquisitions } from "../lib/queries";
import ReservoirButton from "./ReservoirButton";

const RESERVOIRS = [
  { id: "gobind_sagar", name: "Gobind Sagar", basin: "Sutlej" },
  { id: "pong", name: "Pong Dam", basin: "Beas" },
  { id: "thein", name: "Thein Dam", basin: "Ravi" },
] as const;

export default function Sidebar() {
  const view = useAppStore((s) => s.view);
  const selected = useAppStore((s) => s.selected);
  const imageryDateFrom = useAppStore((s) => s.imageryDateFrom);
  const imageryDateTo = useAppStore((s) => s.imageryDateTo);
  const setImageryDateRange = useAppStore((s) => s.setImageryDateRange);
  const openDashboard = useAppStore((s) => s.openDashboard);
  const { data: acquisitions } = useAcquisitions(selected);
  const firstDate = acquisitions?.[0]?.date ?? "";
  const lastDate = acquisitions?.[acquisitions.length - 1]?.date ?? "";
  return (
    <nav className="sidebar">
      <div className="brand">◈ RESERVOIR WATCH</div>
      {RESERVOIRS.map((r) => (
        <ReservoirButton key={r.id} id={r.id} name={r.name} basin={r.basin} />
      ))}
      <div className="date-range-card">
        <div className="date-range-title">Imagery range</div>
        <label>
          <span>From</span>
          <input
            type="date"
            min={firstDate}
            max={imageryDateTo ?? lastDate}
            value={imageryDateFrom ?? ""}
            disabled={!selected || !acquisitions?.length}
            onChange={(e) =>
              setImageryDateRange({ from: e.target.value || null, to: imageryDateTo })
            }
          />
        </label>
        <label>
          <span>To</span>
          <input
            type="date"
            min={imageryDateFrom ?? firstDate}
            max={lastDate}
            value={imageryDateTo ?? ""}
            disabled={!selected || !acquisitions?.length}
            onChange={(e) =>
              setImageryDateRange({ from: imageryDateFrom, to: e.target.value || null })
            }
          />
        </label>
        <button
          type="button"
          disabled={!imageryDateFrom && !imageryDateTo}
          onClick={() => setImageryDateRange({ from: null, to: null })}
        >
          Full range
        </button>
        <div className="date-range-hint">
          {firstDate && lastDate ? `${firstDate} → ${lastDate}` : "Select a reservoir"}
        </div>
      </div>
      <button
        className={`dbtn ${view === "dashboard" ? "active" : ""}`}
        onClick={openDashboard}
      >
        ▦ Dashboard
      </button>
    </nav>
  );
}
