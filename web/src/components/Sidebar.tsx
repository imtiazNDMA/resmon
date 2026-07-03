import { useAppStore } from "../lib/store";
import ReservoirButton from "./ReservoirButton";

const RESERVOIRS = [
  { id: "gobind_sagar", name: "Gobind Sagar", basin: "Sutlej" },
  { id: "pong", name: "Pong Dam", basin: "Beas" },
  { id: "thein", name: "Thein Dam", basin: "Ravi" },
] as const;

export default function Sidebar() {
  const view = useAppStore((s) => s.view);
  const openDashboard = useAppStore((s) => s.openDashboard);
  return (
    <nav className="sidebar">
      <div className="brand">◈ RESERVOIR WATCH</div>
      {RESERVOIRS.map((r) => (
        <ReservoirButton key={r.id} id={r.id} name={r.name} basin={r.basin} />
      ))}
      <button
        className={`dbtn ${view === "dashboard" ? "active" : ""}`}
        onClick={openDashboard}
      >
        ▦ Dashboard
      </button>
    </nav>
  );
}
