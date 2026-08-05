import { GeoJSON } from "react-leaflet";
import type { LeafletMouseEvent, Path } from "leaflet";
import { useSubBasins } from "../../lib/queries";
import { useAppStore } from "../../lib/store";
import type { GeoFC, SubBasinProperties } from "../../types";

/** Sub-basins sit below the river network as a restrained terrain wash. */
const HEADWATER_STYLE = { color: "#526b48", weight: 0.85, fillColor: "#8f9b64", fillOpacity: 0.18 };
const DOWNSTREAM_STYLE = { color: "#667260", weight: 0.7, fillColor: "#b5b27b", fillOpacity: 0.1 };
const HOVER_STYLE = { color: "#ffffff", weight: 1.6, fillColor: "#c8c076", fillOpacity: 0.28 };

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
        const props = feature.properties as SubBasinProperties;
        const resting = styleFor(!!feature?.properties?.is_headwater);
        layer.bindTooltip(
          `Sub-basin HYBAS ${props.hybas_id}<br/>${props.is_headwater ? "headwater" : "downstream"}<br/>next down ${props.next_down || "outlet"}`,
        );
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
