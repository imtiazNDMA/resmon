import { GeoJSON } from "react-leaflet";
import { isExtentStale, isExtentVisible } from "../../lib/extentVisibility";
import { useAcquisitions, useWaterExtent } from "../../lib/queries";
import { useAppStore } from "../../lib/store";

/** Latest vectorised SAR water mask for the selected reservoir. Drawn only when
 *  the timeline sits on the latest acquisition, so the outline never contradicts
 *  older imagery underneath (spec: scrub auto-hide). Stale masks (>14d IST) dim. */
export default function WaterExtentLayer() {
  const selected = useAppStore((s) => s.selected);
  const show = useAppStore((s) => s.showWaterExtent);
  const activeDate = useAppStore((s) => s.activeDate);
  const { data } = useWaterExtent();
  const { data: acqs } = useAcquisitions(selected);
  if (!selected || !show || !data) return null;
  const f = data.features.find((x) => x.properties.reservoir_id === selected);
  if (!f) return null;
  const latest = acqs?.length ? acqs[acqs.length - 1]!.date : null;
  if (!isExtentVisible(activeDate, latest)) return null;
  const stale = isExtentStale(f.properties.acquisition_date);
  return (
      <GeoJSON
        key={`extent-${selected}-${f.properties.acquisition_date}`}
        data={f}
        style={{
          color: "#45f0df",
          weight: 2.2,
          opacity: stale ? 0.5 : 1,
          fillColor: "#18bfc1",
          fillOpacity: stale ? 0.14 : 0.3,
        }}
        onEachFeature={(_, layer) => {
          layer.bindTooltip(
            `Current SAR water extent<br/>${f.properties.acquisition_date}<br/>${f.properties.surface_area_km2.toFixed(1)} km2`,
          );
        }}
      />
  );
}
