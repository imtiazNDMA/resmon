import { describe, expect, it } from "vitest";
import {
  HYDROBASINS_CARTOGRAPHIC_WARNING,
  HYDROBASINS_LEVEL_POLICY,
  HYDROLOGIC_LAYER_STYLES,
  HYDROLOGIC_MAP_PRODUCTS,
  HYDROLOGIC_SIMPLIFICATION_POLICY,
  HYDROLOGIC_SOURCE_HIERARCHY,
} from "./hydrologicMapPolicy";

describe("hydrologic map policy", () => {
  it("defines the four agreed map products", () => {
    expect(HYDROLOGIC_MAP_PRODUCTS.map((p) => p.id)).toEqual([
      "fleet_overview",
      "reservoir_catchment",
      "interactive_analysis",
      "static_export",
    ]);
  });

  it("keeps MERIT Hydro authoritative over HydroBASINS for contributing area", () => {
    expect(HYDROLOGIC_SOURCE_HIERARCHY.contributingArea).toContain("MERIT Hydro");
    expect(HYDROLOGIC_SOURCE_HIERARCHY.basinDisplayUnits).toContain("HydroBASINS");
    expect(HYDROBASINS_CARTOGRAPHIC_WARNING).toContain("display/aggregation units");
  });

  it("separates regional, reservoir, and zoomed HydroBASINS levels", () => {
    expect(HYDROBASINS_LEVEL_POLICY.regionalContext).toBe("hybas_5_or_6");
    expect(HYDROBASINS_LEVEL_POLICY.reservoirOverview).toBe("hybas_7");
    expect(HYDROBASINS_LEVEL_POLICY.zoomedAnalysis).toContain("hybas_8_or_9");
  });

  it("does not style catchment divides as water", () => {
    expect(HYDROLOGIC_LAYER_STYLES.catchment_divide.color).not.toBe(
      HYDROLOGIC_LAYER_STYLES.main_stem.color,
    );
    expect(HYDROLOGIC_LAYER_STYLES.catchment_divide.note).toContain("not read it as water");
  });

  it("requires topology-preserving simplification", () => {
    expect(HYDROLOGIC_SIMPLIFICATION_POLICY.webVectorDegrees).toBe(0.0001);
    expect(HYDROLOGIC_SIMPLIFICATION_POLICY.requirement).toContain("NEXT_DOWN");
  });
});
