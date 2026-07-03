import { useEffect, useRef } from "react";
import { buttonSweep, countTo } from "../lib/motion";
import { useStatus } from "../lib/queries";
import { useAppStore, type ReservoirId } from "../lib/store";

export default function ReservoirButton(props: {
  id: ReservoirId;
  name: string;
  basin: string;
}) {
  const selected = useAppStore((s) => s.selected);
  const view = useAppStore((s) => s.view);
  const selectReservoir = useAppStore((s) => s.selectReservoir);
  const { data: status } = useStatus(props.id);
  const ref = useRef<HTMLButtonElement>(null);
  const fillRef = useRef<HTMLSpanElement>(null);
  const active = view === "map" && selected === props.id;

  useEffect(() => {
    if (fillRef.current && status?.pct_filled != null)
      countTo(fillRef.current, Number(status.pct_filled), 1);
  }, [status?.pct_filled]);

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
