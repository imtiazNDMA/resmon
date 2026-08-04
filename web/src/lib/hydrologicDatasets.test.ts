import { describe, expect, it } from "vitest";
import { datasetIdsForCategory, HYDROLOGIC_DATASETS } from "./hydrologicDatasets";

const byId = new Map(HYDROLOGIC_DATASETS.map((dataset) => [dataset.id, dataset]));

describe("hydrologic dataset catalog", () => {
  it("covers every Phase 8A.2 dataset category", () => {
    expect(datasetIdsForCategory("terrain")).toContain("merit_dem_or_srtm");
    expect(datasetIdsForCategory("basins")).toEqual(
      expect.arrayContaining(["hydrobasins", "merit_hydro"]),
    );
    expect(datasetIdsForCategory("flow_network")).toContain("hydrorivers_or_merit_vectors");
    expect(datasetIdsForCategory("reservoir_geometry")).toEqual(
      expect.arrayContaining(["jrc_global_surface_water", "sentinel1_water_extent"]),
    );
    expect(datasetIdsForCategory("hydromet_dynamic")).toEqual(
      expect.arrayContaining(["era5_land", "gpm_imerg", "modis_snow", "gfs_forecast"]),
    );
    expect(datasetIdsForCategory("context")).toContain("admin_boundaries_context");
    expect(datasetIdsForCategory("provenance")).toContain("layer_provenance");
  });

  it("keeps HydroBASINS as display units and MERIT Hydro as contributing-area authority", () => {
    expect(byId.get("hydrobasins")?.purpose).toContain("display units");
    expect(byId.get("hydrobasins")?.limitations.join(" ")).toContain("MERIT Hydro");
    expect(byId.get("merit_hydro")?.purpose).toContain("Authority");
  });

  it("requires provenance fields for prepared map layers", () => {
    expect(byId.get("layer_provenance")?.requiredFields).toEqual(
      expect.arrayContaining([
        "dataset_id",
        "version",
        "resolution",
        "processed_at",
        "projection",
        "limitations",
      ]),
    );
  });

  it("records limitations for every dataset", () => {
    expect(HYDROLOGIC_DATASETS.every((dataset) => dataset.limitations.length > 0)).toBe(true);
  });
});
