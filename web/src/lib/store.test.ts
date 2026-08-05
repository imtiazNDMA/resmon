import { beforeEach, describe, expect, it } from "vitest";
import { DEFAULT_SAR_COMPOSITE } from "./sarComposites";
import { useAppStore } from "./store";

const s = () => useAppStore.getState();

beforeEach(() => useAppStore.setState(useAppStore.getInitialState()));

describe("app store transitions", () => {
  it("selecting a reservoir enters map view and resets date/playing", () => {
    s().openDashboard();
    s().selectReservoir("gobind_sagar");
    s().setActiveDate("2020-01-05");
    s().setPlaying(true);
    s().selectReservoir("pong");
    expect(s().view).toBe("map");
    expect(s().selected).toBe("pong");
    expect(s().activeDate).toBeNull(); // MapView sets it to latest acquisition
    expect(s().playing).toBe(false); // switching reservoir mid-play stops playback
  });

  it("opening dashboard stops playback but keeps selection", () => {
    s().selectReservoir("thein");
    s().setPlaying(true);
    s().openDashboard();
    expect(s().view).toBe("dashboard");
    expect(s().playing).toBe(false);
    expect(s().selected).toBe("thein");
  });

  it("setActiveDate ignores dates while no reservoir selected", () => {
    s().setActiveDate("2020-01-05");
    expect(s().activeDate).toBeNull();
  });

  it("stores the selected SAR composite", () => {
    expect(s().sarComposite).toBe(DEFAULT_SAR_COMPOSITE);
    s().setSarComposite("water_class");
    expect(s().sarComposite).toBe("water_class");
  });

  it("layer toggles default on and flip independently", () => {
    expect(s().showCatchment).toBe(true);
    expect(s().showWaterExtent).toBe(true);
    expect(s().showFlowEdges).toBe(false);
    s().toggleLayer("catchment");
    expect(s().showCatchment).toBe(false);
    expect(s().showWaterExtent).toBe(true); // independent
    s().toggleLayer("catchment");
    expect(s().showCatchment).toBe(true);
    s().toggleLayer("waterExtent");
    expect(s().showWaterExtent).toBe(false);
  });

  it("sub-basins default off and toggle without disturbing the other layers", () => {
    expect(s().showSubBasins).toBe(false); // opt-in: dozens of polygons over the basemap
    s().toggleLayer("subBasins");
    expect(s().showSubBasins).toBe(true);
    expect(s().showCatchment).toBe(true);
    expect(s().showWaterExtent).toBe(true);
    s().toggleLayer("subBasins");
    expect(s().showSubBasins).toBe(false);
  });

  it("flow paths default off and toggle independently", () => {
    expect(s().showFlowEdges).toBe(false);
    s().toggleLayer("flowEdges");
    expect(s().showFlowEdges).toBe(true);
    expect(s().showCatchment).toBe(true);
    expect(s().showSubBasins).toBe(false);
    expect(s().showWaterExtent).toBe(true);
  });
});
