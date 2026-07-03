import { useEffect, useMemo, useRef } from "react";
import { dockRise } from "../../lib/motion";
import { useAppStore } from "../../lib/store";
import type { Acquisition } from "../../types";

export default function TimelineDock({ acquisitions }: { acquisitions: Acquisition[] }) {
  const activeDate = useAppStore((s) => s.activeDate);
  const setActiveDate = useAppStore((s) => s.setActiveDate);
  const playing = useAppStore((s) => s.playing);
  const setPlaying = useAppStore((s) => s.setPlaying);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (rootRef.current) dockRise(rootRef.current);
  }, []);

  const idx = useMemo(
    () => Math.max(0, acquisitions.findIndex((a) => a.date === activeDate)),
    [acquisitions, activeDate],
  );

  // play mode: advance ~600ms/step, stop at the end (spec motion score)
  useEffect(() => {
    if (!playing) return;
    const t = window.setInterval(() => {
      const next = acquisitions[idx + 1];
      if (next) setActiveDate(next.date);
      else setPlaying(false);
    }, 600);
    return () => window.clearInterval(t);
  }, [playing, idx, acquisitions, setActiveDate, setPlaying]);

  const max = Math.max(...acquisitions.map((a) => a.area_km2));
  const min = Math.min(...acquisitions.map((a) => a.area_km2));
  const denom = Math.max(1, acquisitions.length - 1);
  const points = acquisitions
    .map((a, i) => {
      const x = (i / denom) * 100;
      const y = 100 - ((a.area_km2 - min) / (max - min || 1)) * 100;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <div className="dock" ref={rootRef}>
      <svg className="dock-spark" viewBox="0 0 100 100" preserveAspectRatio="none">
        <polyline
          points={points}
          fill="none"
          stroke="var(--water)"
          strokeWidth="1"
          vectorEffect="non-scaling-stroke"
        />
        <line
          x1={(idx / denom) * 100}
          y1="0"
          x2={(idx / denom) * 100}
          y2="100"
          stroke="var(--text)"
          strokeWidth="1"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <div className="dock-controls">
        <button className="playbtn" onClick={() => setPlaying(!playing)}>
          {playing ? "❚❚" : "▶"}
        </button>
        <input
          type="range"
          min={0}
          max={acquisitions.length - 1}
          value={idx}
          onChange={(e) => setActiveDate(acquisitions[Number(e.target.value)]!.date)}
        />
        <span className="dock-date">{activeDate ?? "—"}</span>
      </div>
    </div>
  );
}
