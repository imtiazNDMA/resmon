import { create } from "zustand";

export type ReservoirId = "gobind_sagar" | "pong" | "thein";
export type View = "map" | "dashboard";

interface AppState {
  view: View;
  selected: ReservoirId | null;
  activeDate: string | null;
  imageryDateFrom: string | null;
  imageryDateTo: string | null;
  playing: boolean;
  showCatchment: boolean;
  showWaterExtent: boolean;
  selectReservoir: (id: ReservoirId) => void;
  openDashboard: () => void;
  setActiveDate: (d: string | null) => void;
  setImageryDateRange: (range: { from: string | null; to: string | null }) => void;
  setPlaying: (p: boolean) => void;
  toggleLayer: (layer: "catchment" | "waterExtent") => void;
}

export const useAppStore = create<AppState>((set, get) => ({
  view: "map",
  selected: null,
  activeDate: null,
  imageryDateFrom: null,
  imageryDateTo: null,
  playing: false,
  showCatchment: true,
  showWaterExtent: true,
  selectReservoir: (id) =>
    set({ view: "map", selected: id, activeDate: null, playing: false }),
  openDashboard: () => set({ view: "dashboard", playing: false }),
  setActiveDate: (d) => {
    if (get().selected !== null) set({ activeDate: d });
  },
  setImageryDateRange: ({ from, to }) =>
    set({ imageryDateFrom: from, imageryDateTo: to, playing: false }),
  setPlaying: (p) => set({ playing: p }),
  toggleLayer: (layer) =>
    set((state) =>
      layer === "catchment"
        ? { showCatchment: !state.showCatchment }
        : { showWaterExtent: !state.showWaterExtent },
    ),
}));
