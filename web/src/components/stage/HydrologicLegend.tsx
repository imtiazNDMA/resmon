import { useHydrologicProvenance } from "../../lib/queries";
import { useAppStore } from "../../lib/store";

export default function HydrologicLegend() {
  const selected = useAppStore((s) => s.selected);
  const showCatchment = useAppStore((s) => s.showCatchment);
  const showSubBasins = useAppStore((s) => s.showSubBasins);
  const showFlowEdges = useAppStore((s) => s.showFlowEdges);
  const showWaterExtent = useAppStore((s) => s.showWaterExtent);
  const { data: provenance } = useHydrologicProvenance(selected);
  const visible = showCatchment || showSubBasins || showFlowEdges || showWaterExtent;
  if (!visible) return null;
  const provenanceByLayer = new Map(provenance?.map((row) => [row.layer_name, row]) ?? []);
  const activeSources = [
    showCatchment ? provenanceByLayer.get("catchment") : undefined,
    showSubBasins ? provenanceByLayer.get("subbasins") : undefined,
    showFlowEdges ? provenanceByLayer.get("flowlines") : undefined,
    showWaterExtent ? provenanceByLayer.get("water_extent") : undefined,
  ].filter((row): row is NonNullable<typeof row> => !!row);

  return (
    <aside className="hydro-legend" aria-label="Hydrologic map legend">
      <div className="hydro-legend-title">Hydrologic layers</div>
      {showCatchment && (
        <div className="hydro-legend-row">
          <span className="legend-swatch catchment" />
          <span>Catchment divide</span>
        </div>
      )}
      {showSubBasins && (
        <>
          <div className="hydro-legend-row">
            <span className="legend-swatch subbasin-headwater" />
            <span>Headwater sub-basin</span>
          </div>
          <div className="hydro-legend-row">
            <span className="legend-swatch subbasin" />
            <span>Downstream sub-basin</span>
          </div>
        </>
      )}
      {showFlowEdges && (
        <div className="hydro-legend-row">
          <span className="legend-line river" />
          <span>Drainage network</span>
        </div>
      )}
      {showWaterExtent && (
        <div className="hydro-legend-row">
          <span className="legend-swatch water" />
          <span>Current SAR water extent</span>
        </div>
      )}
      {activeSources.length > 0 && (
        <div className="hydro-legend-sources">
          {activeSources.map((row) => (
            <div key={row.layer_name}>
              <strong>{row.layer_name.replace("_", " ")}</strong>: {row.source_dataset}
              {row.source_version ? ` ${row.source_version}` : ""}
              {row.source_date ? ` (${row.source_date})` : ""}
            </div>
          ))}
        </div>
      )}
    </aside>
  );
}
