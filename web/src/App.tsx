import { useEffect, useRef } from "react";
import Sidebar from "./components/Sidebar";
import DashboardView from "./components/stage/DashboardView";
import MapView from "./components/stage/MapView";
import { appLoadIn, viewSwap } from "./lib/motion";
import { useAppStore } from "./lib/store";

export default function App() {
  const view = useAppStore((s) => s.view);
  const rootRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);

  // Cleanups revert (not just kill) the tweens: StrictMode double-mounts effects,
  // and a re-run gsap.from() would otherwise record the in-flight opacity-0 state
  // as the animation TARGET, leaving the whole UI permanently dimmed.
  useEffect(() => {
    if (!rootRef.current) return;
    const tl = appLoadIn(rootRef.current);
    return () => {
      tl.revert();
    };
  }, []);

  useEffect(() => {
    if (!stageRef.current) return;
    const tl = viewSwap(stageRef.current, view);
    return () => {
      tl.revert();
    };
  }, [view]);

  return (
    <div className="app" ref={rootRef}>
      <Sidebar />
      <div className="stage" ref={stageRef}>
        {view === "map" ? <MapView /> : <DashboardView />}
      </div>
    </div>
  );
}
