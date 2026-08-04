import { GeoJSON } from "react-leaflet";
import type { LeafletMouseEvent, Path } from "leaflet";
import { useCatchment } from "../../lib/queries";
import { useAppStore } from "../../lib/store";

const CATCHMENT_STYLE = { color: "#d9a45b", weight: 1.5, dashArray: "6 4", fillOpacity: 0.04 };

/** Upstream catchment (HydroBASINS) for the selected reservoir. Dashed sand
 *  outline so it reads as a terrain boundary, not water. Degrades to nothing
 *  on query error or missing feature — never blocks the other layers. */
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
        layer.on({
          mouseover: (event: LeafletMouseEvent) => {
            (event.target as Path).setStyle({ fillOpacity: 1 });
          },
          mouseout: (event: LeafletMouseEvent) => {
            (event.target as Path).setStyle(CATCHMENT_STYLE);
          },
        });
      }}
    />
  );
}
