import { formatDayMonth, isExtentStale } from "../../lib/extentVisibility";
import { useCatchment, useWaterExtent } from "../../lib/queries";
import { useAppStore } from "../../lib/store";

/** Top-right layer toggles + the always-honest extent date chip. A chip disables
 *  (rather than erroring) when its layer has no data for the selected reservoir. */
export default function LayerChips() {
  const selected = useAppStore((s) => s.selected);
  const showCatchment = useAppStore((s) => s.showCatchment);
  const showWaterExtent = useAppStore((s) => s.showWaterExtent);
  const toggleLayer = useAppStore((s) => s.toggleLayer);
  const { data: catchment } = useCatchment();
  const { data: extent } = useWaterExtent();
  if (!selected) return null;
  const hasCatchment = !!catchment?.features.some(
    (f) => f.properties.reservoir_id === selected,
  );
  const extentFeature = extent?.features.find(
    (f) => f.properties.reservoir_id === selected,
  );
  const stale = extentFeature ? isExtentStale(extentFeature.properties.acquisition_date) : false;
  return (
    <div className="layer-chips">
      <button
        className={`layer-chip ${showCatchment ? "on" : ""}`}
        disabled={!hasCatchment}
        onClick={() => toggleLayer("catchment")}
      >
        Catchment
      </button>
      <button
        className={`layer-chip ${showWaterExtent ? "on" : ""}`}
        disabled={!extentFeature}
        onClick={() => toggleLayer("waterExtent")}
      >
        Water extent
      </button>
      {showWaterExtent && extentFeature && (
        <span className={`extent-date-chip ${stale ? "stale" : ""}`}>
          extent · {formatDayMonth(extentFeature.properties.acquisition_date)}
        </span>
      )}
    </div>
  );
}
