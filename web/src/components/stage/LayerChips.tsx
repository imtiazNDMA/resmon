import { useState } from "react";
import { formatDayMonth, isExtentStale } from "../../lib/extentVisibility";
import { BASEMAPS } from "../../lib/basemaps";
import { SAR_COMPOSITES } from "../../lib/sarComposites";
import {
  useCatchment,
  useDistricts,
  useFlowlines,
  usePmdLightning,
  usePmdMonsoon,
  usePmdPredictions,
  usePmdStations,
  usePmdWarnings,
  useSubBasins,
  useWaterExtent,
} from "../../lib/queries";
import { useAppStore } from "../../lib/store";
import { ApiError } from "../../lib/api";

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
  const showSubBasins = useAppStore((s) => s.showSubBasins);
  const showFlowEdges = useAppStore((s) => s.showFlowEdges);
  const showDistricts = useAppStore((s) => s.showDistricts);
  const showWaterExtent = useAppStore((s) => s.showWaterExtent);
  const showPmdStations = useAppStore((s) => s.showPmdStations);
  const showPmdWarnings = useAppStore((s) => s.showPmdWarnings);
  const showPmdMonsoon = useAppStore((s) => s.showPmdMonsoon);
  const showPmdLightning = useAppStore((s) => s.showPmdLightning);
  const pmdLightningHours = useAppStore((s) => s.pmdLightningHours);
  const setPmdLightningHours = useAppStore((s) => s.setPmdLightningHours);
  const showPmdPredHourly = useAppStore((s) => s.showPmdPredHourly);
  const showPmdPredSix = useAppStore((s) => s.showPmdPredSix);
  const showPmdPredTwelve = useAppStore((s) => s.showPmdPredTwelve);
  const showPmdPredDay = useAppStore((s) => s.showPmdPredDay);
  const toggleLayer = useAppStore((s) => s.toggleLayer);
  const { data: catchment } = useCatchment();
  const { data: subbasins } = useSubBasins();
  const { data: flowlines } = useFlowlines(selected);
  const { data: districts } = useDistricts();
  const { data: extent } = useWaterExtent();
  const pmdStations = usePmdStations(open || showPmdStations);
  const pmdWarnings = usePmdWarnings(open || showPmdWarnings);
  const pmdMonsoon = usePmdMonsoon(open || showPmdMonsoon);
  const pmdLightning = usePmdLightning(pmdLightningHours, open || showPmdLightning);
  const pmdPredHourly = usePmdPredictions("pmd_pred_hourtpe", open || showPmdPredHourly);
  const pmdPredSix = usePmdPredictions("pmd_pred_sixtpe", open || showPmdPredSix);
  const pmdPredTwelve = usePmdPredictions("pmd_pred_twelvetpe", open || showPmdPredTwelve);
  const pmdPredDay = usePmdPredictions("pmd_pred_daytpe", open || showPmdPredDay);
  const hasCatchment = !!selected && !!catchment?.features.some(
    (f) => f.properties.reservoir_id === selected,
  );
  const extentFeature = selected ? extent?.features.find(
    (f) => f.properties.reservoir_id === selected,
  ) : undefined;
  const hasSubBasins =
    !!selected && !!subbasins?.features.some((f) => f.properties.reservoir_id === selected);
  const hasFlowPaths = !!selected && !!flowlines?.features.length;
  const hasDistricts = !!districts?.features.length;
  const pmdDisabled = pmdStations.error instanceof ApiError && pmdStations.error.status === 503;
  const pmdWarningsDisabled = pmdWarnings.error instanceof ApiError && pmdWarnings.error.status === 503;
  const pmdMonsoonDisabled = pmdMonsoon.error instanceof ApiError && pmdMonsoon.error.status === 503;
  const pmdLightningDisabled = pmdLightning.error instanceof ApiError && pmdLightning.error.status === 503;
  const pmdPredDisabled =
    (pmdPredHourly.error instanceof ApiError && pmdPredHourly.error.status === 503) ||
    (pmdPredSix.error instanceof ApiError && pmdPredSix.error.status === 503) ||
    (pmdPredTwelve.error instanceof ApiError && pmdPredTwelve.error.status === 503) ||
    (pmdPredDay.error instanceof ApiError && pmdPredDay.error.status === 503);
  const hasPmdStations = !!pmdStations.data?.features.length;
  const hasPmdWarnings = !!pmdWarnings.data?.features.length;
  const hasPmdMonsoon = !!pmdMonsoon.data?.features.length;
  const hasPmdLightning = !!pmdLightning.data?.features.length;
  const hasPmdPredHourly = !!pmdPredHourly.data?.available;
  const hasPmdPredSix = !!pmdPredSix.data?.available;
  const hasPmdPredTwelve = !!pmdPredTwelve.data?.available;
  const hasPmdPredDay = !!pmdPredDay.data?.available;
  const stale = extentFeature ? isExtentStale(extentFeature.properties.acquisition_date) : false;
  const activeBasemap = BASEMAPS.find((b) => b.id === basemap)?.name ?? "Basemap";
  const activeComposite = SAR_COMPOSITES.find((c) => c.id === sarComposite)?.name ?? "SAR";
  const activeOverlays = [
    showCatchment && hasCatchment,
    showSubBasins && hasSubBasins,
    showFlowEdges && hasFlowPaths,
    showDistricts && hasDistricts,
    showWaterExtent && extentFeature,
    showPmdStations && hasPmdStations,
    showPmdWarnings && hasPmdWarnings,
    showPmdMonsoon && hasPmdMonsoon,
    showPmdLightning && hasPmdLightning,
    showPmdPredHourly && hasPmdPredHourly,
    showPmdPredSix && hasPmdPredSix,
    showPmdPredTwelve && hasPmdPredTwelve,
    showPmdPredDay && hasPmdPredDay,
  ].filter(Boolean).length;
  const weatherUnavailable =
    pmdDisabled ||
    pmdWarningsDisabled ||
    pmdMonsoonDisabled ||
    pmdLightningDisabled ||
    pmdPredDisabled;
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
                className={`map-control-btn ${showSubBasins ? "on" : ""}`}
                disabled={!hasSubBasins}
                onClick={() => toggleLayer("subBasins")}
              >
                Sub-basins
              </button>
              <button
                type="button"
                className={`map-control-btn ${showFlowEdges ? "on" : ""}`}
                disabled={!hasFlowPaths}
                onClick={() => toggleLayer("flowEdges")}
              >
                Drainage network
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
          <div className="map-control-section">
            <div className="map-control-title">Weather</div>
            <div className="overlay-stack">
              <button
                type="button"
                className={`map-control-btn ${showPmdStations ? "on" : ""}`}
                disabled={pmdDisabled || !hasPmdStations}
                onClick={() => toggleLayer("pmdStations")}
              >
                PMD stations
              </button>
              <button
                type="button"
                className={`map-control-btn ${showPmdWarnings ? "on" : ""}`}
                disabled={pmdWarningsDisabled || !hasPmdWarnings}
                onClick={() => toggleLayer("pmdWarnings")}
              >
                PMD warnings
              </button>
              <button
                type="button"
                className={`map-control-btn ${showPmdMonsoon ? "on" : ""}`}
                disabled={pmdMonsoonDisabled || !hasPmdMonsoon}
                onClick={() => toggleLayer("pmdMonsoon")}
              >
                Monsoon warnings
              </button>
              <button
                type="button"
                className={`map-control-btn ${showPmdLightning ? "on" : ""}`}
                disabled={pmdLightningDisabled || !hasPmdLightning}
                onClick={() => toggleLayer("pmdLightning")}
              >
                Lightning
              </button>
              <div style={{ borderTop: "1px solid #eee", marginTop: "8px", paddingTop: "8px" }}>
                <div style={{ fontSize: "11px", fontWeight: 600, marginBottom: "6px" }}>Forecast</div>
                <button
                  type="button"
                  className={`map-control-btn ${showPmdPredHourly ? "on" : ""}`}
                  disabled={pmdPredDisabled || !hasPmdPredHourly}
                  onClick={() => toggleLayer("pmdPredHourly")}
                >
                  1h precip
                </button>
                <button
                  type="button"
                  className={`map-control-btn ${showPmdPredSix ? "on" : ""}`}
                  disabled={pmdPredDisabled || !hasPmdPredSix}
                  onClick={() => toggleLayer("pmdPredSix")}
                >
                  6h precip
                </button>
                <button
                  type="button"
                  className={`map-control-btn ${showPmdPredTwelve ? "on" : ""}`}
                  disabled={pmdPredDisabled || !hasPmdPredTwelve}
                  onClick={() => toggleLayer("pmdPredTwelve")}
                >
                  12h precip
                </button>
                <button
                  type="button"
                  className={`map-control-btn ${showPmdPredDay ? "on" : ""}`}
                  disabled={pmdPredDisabled || !hasPmdPredDay}
                  onClick={() => toggleLayer("pmdPredDay")}
                >
                  24h precip
                </button>
              </div>
              <div className="weather-window-row" aria-label="Lightning lookback window">
                {[1, 6, 12, 24, 48].map((hours) => (
                  <button
                    key={hours}
                    type="button"
                    className={`weather-window-btn ${pmdLightningHours === hours ? "on" : ""}`}
                    onClick={() => setPmdLightningHours(hours)}
                  >
                    {hours}h
                  </button>
                ))}
              </div>
            </div>
            <small className="map-control-note">
              {weatherUnavailable
                ? "PMD credentials are not configured on the backend."
                : pmdStations.isLoading ||
                    pmdWarnings.isLoading ||
                    pmdMonsoon.isLoading ||
                    pmdLightning.isLoading ||
                    pmdPredHourly.isLoading ||
                    pmdPredSix.isLoading ||
                    pmdPredTwelve.isLoading ||
                    pmdPredDay.isLoading
                  ? "Checking PMD weather availability..."
                  : `${pmdStations.data?.features.length ?? 0} stations · ${pmdWarnings.data?.features.length ?? 0} warnings · ${pmdMonsoon.data?.features.length ?? 0} monsoon · ${pmdLightning.data?.features.length ?? 0} strikes${hasPmdPredHourly || hasPmdPredSix || hasPmdPredTwelve || hasPmdPredDay ? " · forecast available" : ""}`}
            </small>
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
