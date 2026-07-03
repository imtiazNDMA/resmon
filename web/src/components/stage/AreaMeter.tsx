import gsap from "gsap";
import { useEffect, useMemo, useRef } from "react";
import { countTo, meterTo } from "../../lib/motion";
import { useAppStore } from "../../lib/store";
import type { Acquisition } from "../../types";

export default function AreaMeter({ acquisitions }: { acquisitions: Acquisition[] }) {
  const activeDate = useAppStore((s) => s.activeDate);
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
  );
}
