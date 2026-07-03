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

  useEffect(() => {
    if (rootRef.current) appLoadIn(rootRef.current);
  }, []);

  useEffect(() => {
    if (stageRef.current) viewSwap(stageRef.current, view);
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
