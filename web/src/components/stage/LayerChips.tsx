import { useState } from "react";
import { formatDayMonth, isExtentStale } from "../../lib/extentVisibility";
import { BASEMAPS } from "../../lib/basemaps";
import { SAR_COMPOSITES } from "../../lib/sarComposites";
import { useCatchment, useDistricts, useWaterExtent } from "../../lib/queries";
import { useAppStore } from "../../lib/store";

/** Collapsible map controls + the always-honest extent date chip. A chip disables
 *  (rather than erroring) when its layer has no data for the selected reservoir. */
export default function LayerChips() {
  const [open, setOpen] = useState(false);
  const selected = useAppStore((s) => s.selected);
  const basemap = useAppStore((s) => s.basemap);
  const setBasemap = useAppStore((s) => s.setBasemap);
  const sarComposite = useAppStore((s) => s.sarComposite);
  const setSarComposite = useAppStore((s) => s.setSarComposite);
  const showCatchment = useAppStore((s) => s.showCatchment);
  const showDistricts = useAppStore((s) => s.showDistricts);
  const showWaterExtent = useAppStore((s) => s.showWaterExtent);
  const toggleLayer = useAppStore((s) => s.toggleLayer);
  const { data: catchment } = useCatchment();
  const { data: districts } = useDistricts();
  const { data: extent } = useWaterExtent();
  const hasCatchment = !!selected && !!catchment?.features.some(
    (f) => f.properties.reservoir_id === selected,
  );
  const extentFeature = selected ? extent?.features.find(
    (f) => f.properties.reservoir_id === selected,
  ) : undefined;
  const hasDistricts = !!districts?.features.length;
  const stale = extentFeature ? isExtentStale(extentFeature.properties.acquisition_date) : false;
  const activeBasemap = BASEMAPS.find((b) => b.id === basemap)?.name ?? "Basemap";
  const activeComposite = SAR_COMPOSITES.find((c) => c.id === sarComposite)?.name ?? "SAR";
  const activeOverlays = [showCatchment && hasCatchment, showDistricts && hasDistricts, showWaterExtent && extentFeature].filter(Boolean).length;
  return (
    <div className={`map-control-panel ${open ? "open" : "collapsed"}`} aria-label="Map controls">
      <button
        type="button"
        className="map-control-header"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span>
          <strong>Map controls</strong>
          <small>{activeBasemap} · {activeComposite} · {activeOverlays} overlays</small>
        </span>
        <span className="map-control-caret">{open ? "×" : "☰"}</span>
      </button>
      {open && (
        <>
          <div className="map-control-section">
            <div className="map-control-title">Basemap</div>
            <div className="basemap-grid">
              {BASEMAPS.map((b) => (
                <button
                  key={b.id}
                  type="button"
                  className={`map-control-btn ${basemap === b.id ? "on" : ""}`}
                  onClick={() => setBasemap(b.id)}
                >
                  {b.name}
                </button>
              ))}
            </div>
          </div>
          <div className="map-control-section">
            <div className="map-control-title">Overlays</div>
            <div className="overlay-stack">
              <button
                type="button"
                className={`map-control-btn ${showCatchment ? "on" : ""}`}
                disabled={!hasCatchment}
                onClick={() => toggleLayer("catchment")}
              >
                Catchment
              </button>
              <button
                type="button"
                className={`map-control-btn ${showDistricts ? "on" : ""}`}
                disabled={!hasDistricts}
                onClick={() => toggleLayer("districts")}
              >
                Districts
              </button>
              <button
                type="button"
                className={`map-control-btn ${showWaterExtent ? "on" : ""}`}
                disabled={!extentFeature}
                onClick={() => toggleLayer("waterExtent")}
              >
                Water extent
              </button>
            </div>
          </div>
          <div className="map-control-section">
            <div className="map-control-title">SAR composite</div>
            <div className="composite-stack">
              {SAR_COMPOSITES.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  className={`map-control-btn ${sarComposite === c.id ? "on" : ""}`}
                  disabled={!selected}
                  onClick={() => setSarComposite(c.id)}
                >
                  {c.name}
                </button>
              ))}
            </div>
          </div>
          {showWaterExtent && extentFeature && (
            <span className={`extent-date-chip ${stale ? "stale" : ""}`}>
              extent · {formatDayMonth(extentFeature.properties.acquisition_date)}
            </span>
          )}
        </>
      )}
    </div>
  );
}
