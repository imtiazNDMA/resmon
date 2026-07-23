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
    if (!rootRef.current) return;
    const tween = dockRise(rootRef.current); // gsap.from: revert on StrictMode remount
    return () => {
      tween.revert();
    };
  }, []);

  const idx = useMemo(
    () => acquisitions.findIndex((a) => a.date === activeDate),
    [acquisitions, activeDate],
  );
  const safeIdx = idx >= 0 ? idx : Math.max(0, acquisitions.length - 1);
  const canGoPrevious = safeIdx > 0;
  const canGoNext = safeIdx < acquisitions.length - 1;

  const moveTo = (offset: number) => {
    const acquisition = acquisitions[safeIdx + offset];
    if (acquisition) setActiveDate(acquisition.date);
  };

  // play mode: gentle enough for SAR tiles to load and crossfade between scenes
  useEffect(() => {
    if (!playing) return;
    const t = window.setInterval(() => {
      const next = acquisitions[safeIdx + 1];
      if (next) setActiveDate(next.date);
      else setPlaying(false);
    }, 1800);
    return () => window.clearInterval(t);
  }, [playing, safeIdx, acquisitions, setActiveDate, setPlaying]);

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
          x1={(safeIdx / denom) * 100}
          y1="0"
          x2={(safeIdx / denom) * 100}
          y2="100"
          stroke="var(--text)"
          strokeWidth="1"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <div className="dock-controls">
        <button
          className="timeline-btn"
          type="button"
          aria-label="Previous acquisition"
          title="Previous acquisition"
          disabled={!canGoPrevious}
          onClick={() => moveTo(-1)}
        >
          ‹
        </button>
        <button
          className="timeline-btn"
          type="button"
          aria-label="Play timeline"
          title="Play timeline"
          disabled={playing || !canGoNext}
          onClick={() => setPlaying(true)}
        >
          ▶
        </button>
        <button
          className="timeline-btn"
          type="button"
          aria-label="Pause timeline"
          title="Pause timeline"
          disabled={!playing}
          onClick={() => setPlaying(false)}
        >
          ❚❚
        </button>
        <button
          className="timeline-btn"
          type="button"
          aria-label="Next acquisition"
          title="Next acquisition"
          disabled={!canGoNext}
          onClick={() => moveTo(1)}
        >
          ›
        </button>
        <input
          type="range"
          min={0}
          max={acquisitions.length - 1}
          value={safeIdx}
          onChange={(e) => setActiveDate(acquisitions[Number(e.target.value)]!.date)}
        />
        <span className="dock-date">{idx >= 0 ? activeDate : "-"}</span>
      </div>
    </div>
  );
}
