import { create } from "zustand";
import { DEFAULT_BASEMAP, type BasemapId } from "./basemaps";
import { DEFAULT_SAR_COMPOSITE, type SarCompositeId } from "./sarComposites";

export type ReservoirId = "gobind_sagar" | "pong" | "thein";
export type View = "map" | "dashboard";

interface AppState {
  view: View;
  selected: ReservoirId | null;
  activeDate: string | null;
  imageryDateFrom: string | null;
  imageryDateTo: string | null;
  basemap: BasemapId;
  sarComposite: SarCompositeId;
  playing: boolean;
  showCatchment: boolean;
  showSubBasins: boolean;
  showFlowEdges: boolean;
  showDistricts: boolean;
  showWaterExtent: boolean;
  showPmdStations: boolean;
  showPmdWarnings: boolean;
  showPmdMonsoon: boolean;
  showPmdLightning: boolean;
  pmdLightningHours: number;
  selectReservoir: (id: ReservoirId) => void;
  openDashboard: () => void;
  setActiveDate: (d: string | null) => void;
  setImageryDateRange: (range: { from: string | null; to: string | null }) => void;
  setBasemap: (basemap: BasemapId) => void;
  setSarComposite: (composite: SarCompositeId) => void;
  setPlaying: (p: boolean) => void;
  toggleLayer: (
    layer:
      | "catchment"
      | "subBasins"
      | "flowEdges"
      | "districts"
      | "waterExtent"
      | "pmdStations"
      | "pmdWarnings"
      | "pmdMonsoon"
      | "pmdLightning"
  ) => void;
  setPmdLightningHours: (hours: number) => void;
}

export const useAppStore = create<AppState>((set, get) => ({
  view: "map",
  selected: null,
  activeDate: null,
  imageryDateFrom: null,
  imageryDateTo: null,
  basemap: DEFAULT_BASEMAP,
  sarComposite: DEFAULT_SAR_COMPOSITE,
  playing: false,
  showCatchment: false,
  showSubBasins: false,
  showFlowEdges: false,
  showDistricts: false,
  showWaterExtent: false,
  showPmdStations: false,
  showPmdWarnings: false,
  showPmdMonsoon: false,
  showPmdLightning: false,
  pmdLightningHours: 1,
  selectReservoir: (id) =>
    set({
      view: "map",
      selected: id,
      activeDate: null,
      playing: false,
      showCatchment: true,
      showSubBasins: true,
      showFlowEdges: true,
    }),
  openDashboard: () => set({ view: "dashboard", playing: false }),
  setActiveDate: (d) => {
    if (get().selected !== null) set({ activeDate: d });
  },
  setImageryDateRange: ({ from, to }) =>
    set({ imageryDateFrom: from, imageryDateTo: to, playing: false }),
  setBasemap: (basemap) => set({ basemap }),
  setSarComposite: (sarComposite) => set({ sarComposite }),
  setPlaying: (p) => set({ playing: p }),
  toggleLayer: (layer) =>
    set((state) =>
      layer === "catchment"
        ? { showCatchment: !state.showCatchment }
        : layer === "subBasins"
          ? { showSubBasins: !state.showSubBasins }
          : layer === "flowEdges"
            ? { showFlowEdges: !state.showFlowEdges }
            : layer === "districts"
              ? { showDistricts: !state.showDistricts }
              : layer === "waterExtent"
                ? { showWaterExtent: !state.showWaterExtent }
                : layer === "pmdStations"
                  ? { showPmdStations: !state.showPmdStations }
                  : layer === "pmdWarnings"
                    ? { showPmdWarnings: !state.showPmdWarnings }
                    : layer === "pmdMonsoon"
                      ? { showPmdMonsoon: !state.showPmdMonsoon }
                      : { showPmdLightning: !state.showPmdLightning },
    ),
  setPmdLightningHours: (hours) => set({ pmdLightningHours: Math.min(48, Math.max(1, hours)) }),
}));
