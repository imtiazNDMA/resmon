import { GeoJSON } from "react-leaflet";
import type { LeafletMouseEvent, Path } from "leaflet";
import { useCatchment } from "../../lib/queries";
import { useAppStore } from "../../lib/store";

const CATCHMENT_STYLE = {
  color: "#ff1e1e",
  weight: 3.2,
  opacity: 1,
  fillColor: "#d9d5a5",
  fillOpacity: 0.16,
};
/** Hover lifts the catchment to a purple wash. mouseout restores CATCHMENT_STYLE
 *  wholesale, so the colour reverts with the opacity. */
const CATCHMENT_HOVER_STYLE = { color: "#ffffff", weight: 4.2, fillOpacity: 0.24 };

/** Upstream catchment (HydroBASINS) for the selected reservoir. Drawn as the
 *  hydroshed boundary: a strong red divide over terrain, like a static GIS map. */
export default function CatchmentLayer() {
  const selected = useAppStore((s) => s.selected);
  const show = useAppStore((s) => s.showCatchment);
  const { data } = useCatchment();
  if (!selected || !show || !data) return null;
  const f = data.features.find((x) => x.properties.reservoir_id === selected);
  if (!f) return null;
  return (
    <GeoJSON
      key={`catchment-${selected}`}
      data={f}
      style={CATCHMENT_STYLE}
      onEachFeature={(_, layer) => {
        layer.bindTooltip("Upstream catchment divide<br/>HydroBASINS-derived boundary");
        layer.on({
          mouseover: (event: LeafletMouseEvent) => {
            (event.target as Path).setStyle(CATCHMENT_HOVER_STYLE);
          },
          mouseout: (event: LeafletMouseEvent) => {
            (event.target as Path).setStyle(CATCHMENT_STYLE);
          },
        });
      }}
    />
  );
}
