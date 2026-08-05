import { GeoJSON } from "react-leaflet";
import type { LeafletMouseEvent, Path } from "leaflet";
import { useSubBasins } from "../../lib/queries";
import { useAppStore } from "../../lib/store";
import type { GeoFC, SubBasinProperties } from "../../types";

/** Headwaters — the upper catchment — carry the purple fill; everything downstream is a
 *  faint outline so the eye lands on the top of the basin, not the whole drainage. */
const HEADWATER_STYLE = { color: "#c9a0f0", weight: 1, fillColor: "#a06bd4", fillOpacity: 0.28 };
const DOWNSTREAM_STYLE = { color: "#8c93a8", weight: 0.6, fillColor: "#8c93a8", fillOpacity: 0.04 };
const HOVER_STYLE = { color: "#a06bd4", fillColor: "#a06bd4", fillOpacity: 0.8 };

const styleFor = (isHeadwater: boolean) => (isHeadwater ? HEADWATER_STYLE : DOWNSTREAM_STYLE);

/** Un-dissolved HydroBASINS sub-basins for the selected reservoir — the individual units
 *  that `CatchmentLayer` draws as one outline. Off by default (see store): a level-7
 *  catchment is dozens of polygons and would swamp the basemap. Degrades to nothing on
 *  query error or missing features, same contract as the other overlays.
 *
 *  One GeoJSON layer with a style callback rather than a component per basin, so toggling
 *  reconciles a single layer group instead of N children. */
export default function SubBasinLayer() {
  const selected = useAppStore((s) => s.selected);
  const show = useAppStore((s) => s.showSubBasins);
  const { data } = useSubBasins();
  if (!selected || !show || !data) return null;
  const features = data.features.filter((f) => f.properties.reservoir_id === selected);
  if (features.length === 0) return null;
  const collection: GeoFC<SubBasinProperties> = { type: "FeatureCollection", features };
  return (
    <GeoJSON
      key={`subbasins-${selected}`}
      data={collection}
      style={(feature) => styleFor(!!feature?.properties?.is_headwater)}
      onEachFeature={(feature, layer) => {
        const resting = styleFor(!!feature?.properties?.is_headwater);
        layer.on({
          mouseover: (event: LeafletMouseEvent) => {
            (event.target as Path).setStyle(HOVER_STYLE);
          },
          mouseout: (event: LeafletMouseEvent) => {
            (event.target as Path).setStyle(resting);
          },
        });
      }}
    />
  );
}
