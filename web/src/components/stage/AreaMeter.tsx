import gsap from "gsap";
import { useEffect, useMemo, useRef } from "react";
import { countTo, meterTo } from "../../lib/motion";
import { useReservoirs } from "../../lib/queries";
import { useAppStore } from "../../lib/store";
import type { Acquisition } from "../../types";

export default function AreaMeter({ acquisitions }: { acquisitions: Acquisition[] }) {
  const selected = useAppStore((s) => s.selected);
  const activeDate = useAppStore((s) => s.activeDate);
  const { data: reservoirs } = useReservoirs();
  const fillRef = useRef<HTMLDivElement>(null);
  const numRef = useRef<HTMLDivElement>(null);

  const { min, max } = useMemo(
    () => ({
      min: Math.min(...acquisitions.map((a) => a.area_km2)),
      max: Math.max(...acquisitions.map((a) => a.area_km2)),
    }),
    [acquisitions],
  );
  const active = acquisitions.find((a) => a.date === activeDate);
  const reservoir = reservoirs?.find((r) => r.reservoir_id === selected);

  const valueOrDash = (value: number | null | undefined, decimals: number) =>
    value == null ? "—" : value.toFixed(decimals);

  useEffect(() => {
    if (!active || !fillRef.current || !numRef.current) return;
    meterTo(fillRef.current, (active.area_km2 - min) / (max - min || 1));
    countTo(numRef.current, active.area_km2, 1);
  }, [active, min, max]);

  // idle shimmer: slow sine on the fill's gradient position (spec motion score)
  useEffect(() => {
    if (!fillRef.current) return;
    const tween = gsap.to(fillRef.current, {
      backgroundPosition: "0 12px",
      duration: 2.4,
      yoyo: true,
      repeat: -1,
      ease: "sine.inOut",
    });
    return () => {
      tween.kill();
    };
  }, []);

  return (
    <div className="estimate-panel">
      <div className="estimate-head">
        <span>Current Estimate</span>
        <span>{active?.historical_date ?? active?.date ?? "—"}</span>
      </div>
      {active?.is_extrapolated && <div className="estimate-warning">Extrapolated</div>}
      <div className="estimate-body">
        <div className="meter">
          <div className="meter-label">km²</div>
          <div className="meter-tube">
            <div className="meter-fill" ref={fillRef} />
          </div>
          <div className="meter-num" ref={numRef}>
            —
          </div>
          <div className="meter-minmax">
            {min.toFixed(0)}–{max.toFixed(0)}
          </div>
        </div>
        <div className="estimate-kpis">
          <div>
            <span>Current reservoir level</span>
            <strong>{valueOrDash(active?.level_m, 2)} m</strong>
          </div>
          <div>
            <span>Current live storage</span>
            <strong>{valueOrDash(active?.live_storage_bcm, 3)} BCM</strong>
          </div>
          <div>
            <span>Storage as % of live capacity at FRL</span>
            <strong>{valueOrDash(active?.pct_filled, 1)}%</strong>
          </div>
          <div>
            <span>Area/storage correlation</span>
            <strong>
              {active?.surface_area_correlation == null
                ? "—"
                : `r = ${active.surface_area_correlation.toFixed(2)}`}
            </strong>
          </div>
          <div>
            <span>Full reservoir level</span>
            <strong>{valueOrDash(reservoir?.frl_m, 2)} m</strong>
          </div>
          <div>
            <span>Live capacity at FRL</span>
            <strong>{valueOrDash(reservoir?.live_capacity_bcm, 3)} BCM</strong>
          </div>
        </div>
      </div>
    </div>
  );
}
