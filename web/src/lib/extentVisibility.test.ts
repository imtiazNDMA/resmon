import { describe, expect, it } from "vitest";
import {
  extentAgeDays,
  formatDayMonth,
  isExtentStale,
  isExtentVisible,
} from "./extentVisibility";

describe("isExtentVisible (extent only shows at the latest timeline date)", () => {
  it("visible when the timeline sits on the latest acquisition", () => {
    expect(isExtentVisible("2026-06-12", "2026-06-12")).toBe(true);
  });
  it("hidden when scrubbed back", () => {
    expect(isExtentVisible("2026-05-01", "2026-06-12")).toBe(false);
  });
  it("hidden while the timeline has no date yet", () => {
    expect(isExtentVisible(null, "2026-06-12")).toBe(false);
  });
  it("hidden when there are no acquisitions", () => {
    expect(isExtentVisible("2026-06-12", null)).toBe(false);
    expect(isExtentVisible("2026-06-12", undefined)).toBe(false);
  });
  it("tolerates datetime-formatted date strings", () => {
    expect(isExtentVisible("2026-06-12", "2026-06-12T00:00:00")).toBe(true);
  });
});

describe("staleness (age > 14 days, mirrors data_staleness_threshold_days)", () => {
  it("boundary: 13 and 14 days old are fresh, 15 is stale", () => {
    expect(isExtentStale("2026-06-21", "2026-07-04")).toBe(false); // 13d
    expect(isExtentStale("2026-06-20", "2026-07-04")).toBe(false); // 14d
    expect(isExtentStale("2026-06-19", "2026-07-04")).toBe(true); // 15d
  });
  it("extentAgeDays counts calendar days", () => {
    expect(extentAgeDays("2026-07-01", "2026-07-04")).toBe(3);
    expect(extentAgeDays("2026-07-04", "2026-07-04")).toBe(0);
  });
});

describe("formatDayMonth", () => {
  it("renders the chip date", () => {
    expect(formatDayMonth("2026-06-12")).toBe("12 Jun");
  });
});
