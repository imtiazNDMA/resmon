import { beforeEach, describe, expect, it } from "vitest";
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

  it("changes basemaps without resetting timeline or overlays", () => {
    s().selectReservoir("pong");
    s().setActiveDate("2026-07-16");
    s().toggleLayer("districts");
    s().setBasemap("dark");
    expect(s().basemap).toBe("dark");
    expect(s().activeDate).toBe("2026-07-16");
    expect(s().selected).toBe("pong");
    expect(s().showDistricts).toBe(true);
  });

  it("changes SAR composites without resetting basemap or overlays", () => {
    s().setBasemap("dark");
    s().toggleLayer("catchment");
    s().setSarComposite("false_color");
    expect(s().sarComposite).toBe("false_color");
    expect(s().basemap).toBe("dark");
    expect(s().showCatchment).toBe(true);
  });

  it("setActiveDate ignores dates while no reservoir selected", () => {
    s().setActiveDate("2020-01-05");
    expect(s().activeDate).toBeNull();
  });

  it("layer toggles default off and flip independently", () => {
    expect(s().showCatchment).toBe(false);
    expect(s().showDistricts).toBe(false);
    expect(s().showWaterExtent).toBe(false);
    s().toggleLayer("catchment");
    expect(s().showCatchment).toBe(true);
    expect(s().showDistricts).toBe(false);
    expect(s().showWaterExtent).toBe(false); // independent
    s().toggleLayer("catchment");
    expect(s().showCatchment).toBe(false);
    s().toggleLayer("districts");
    expect(s().showDistricts).toBe(true);
    s().toggleLayer("waterExtent");
    expect(s().showWaterExtent).toBe(true);
  });
});
