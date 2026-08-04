import { create } from "zustand";
import { DEFAULT_SAR_COMPOSITE, type SarCompositeId } from "./sarComposites";

export type ReservoirId = "gobind_sagar" | "pong" | "thein";
export type View = "map" | "dashboard";

interface AppState {
  view: View;
  selected: ReservoirId | null;
  activeDate: string | null;
  imageryDateFrom: string | null;
  imageryDateTo: string | null;
  sarComposite: SarCompositeId;
  playing: boolean;
  showCatchment: boolean;
  showSubBasins: boolean;
  showFlowEdges: boolean;
  showWaterExtent: boolean;
  selectReservoir: (id: ReservoirId) => void;
  openDashboard: () => void;
  setActiveDate: (d: string | null) => void;
  setImageryDateRange: (range: { from: string | null; to: string | null }) => void;
  setSarComposite: (id: SarCompositeId) => void;
  setPlaying: (p: boolean) => void;
  toggleLayer: (layer: "catchment" | "subBasins" | "flowEdges" | "waterExtent") => void;
}

export const useAppStore = create<AppState>((set, get) => ({
  view: "map",
  selected: null,
  activeDate: null,
  imageryDateFrom: null,
  imageryDateTo: null,
  sarComposite: DEFAULT_SAR_COMPOSITE,
  playing: false,
  showCatchment: true,
  showSubBasins: false, // opt-in: N polygons is a lot of ink over the base imagery
  showFlowEdges: false,
  showWaterExtent: true,
  selectReservoir: (id) =>
    set({ view: "map", selected: id, activeDate: null, playing: false }),
  openDashboard: () => set({ view: "dashboard", playing: false }),
  setActiveDate: (d) => {
    if (get().selected !== null) set({ activeDate: d });
  },
  setImageryDateRange: ({ from, to }) =>
    set({ imageryDateFrom: from, imageryDateTo: to, playing: false }),
  setSarComposite: (id) => set({ sarComposite: id }),
  setPlaying: (p) => set({ playing: p }),
  toggleLayer: (layer) =>
    set((state) => {
      if (layer === "catchment") return { showCatchment: !state.showCatchment };
      if (layer === "subBasins") return { showSubBasins: !state.showSubBasins };
      if (layer === "flowEdges") return { showFlowEdges: !state.showFlowEdges };
      return { showWaterExtent: !state.showWaterExtent };
    }),
}));
