import { useEffect, useRef } from "react";
import { buttonSweep, countTo } from "../lib/motion";
import { useAcquisitions, useStatus } from "../lib/queries";
import { useAppStore, type ReservoirId } from "../lib/store";

export default function ReservoirButton(props: {
  id: ReservoirId;
  name: string;
  basin: string;
}) {
  const selected = useAppStore((s) => s.selected);
  const view = useAppStore((s) => s.view);
  const activeDate = useAppStore((s) => s.activeDate);
  const selectReservoir = useAppStore((s) => s.selectReservoir);
  const { data: status } = useStatus(props.id);
  const ref = useRef<HTMLButtonElement>(null);
  const fillRef = useRef<HTMLSpanElement>(null);
  const active = view === "map" && selected === props.id;
  const { data: acquisitions } = useAcquisitions(active ? props.id : null);
  const activeAcquisition = acquisitions?.find((a) => a.date === activeDate);
  const displayedPct = active && activeDate ? activeAcquisition?.pct_filled : status?.pct_filled;

  useEffect(() => {
    if (!fillRef.current) return;
    if (displayedPct == null) {
      fillRef.current.textContent = "—";
      return;
    }
    countTo(fillRef.current, Number(displayedPct), 1);
  }, [displayedPct]);

  return (
    <button
      ref={ref}
      className={`rbtn ${active ? "active" : ""}`}
      onClick={() => {
        selectReservoir(props.id);
        if (ref.current) buttonSweep(ref.current);
      }}
    >
      <span className="rbtn-name">{props.name}</span>
      <span className="rbtn-sub">
        {props.basin} · <span ref={fillRef}>—</span>%
      </span>
    </button>
  );
}
