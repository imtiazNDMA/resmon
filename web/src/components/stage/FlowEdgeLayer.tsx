import { GeoJSON } from "react-leaflet";
import type { LeafletMouseEvent, Path, PathOptions } from "leaflet";
import { useFlowEdges } from "../../lib/queries";
import { useAppStore } from "../../lib/store";
import type { FlowEdgeProperties, GeoFC } from "../../types";

const FLOW_STYLE: PathOptions = {
  color: "#63d7ff",
  weight: 1.4,
  opacity: 0.62,
  dashArray: "7 7",
  lineCap: "round",
  className: "flow-edge-path",
};
const HEADWATER_FLOW_STYLE: PathOptions = {
  color: "#bdf4ff",
  weight: 1.9,
  opacity: 0.82,
  dashArray: "9 7",
  lineCap: "round",
  className: "flow-edge-path flow-edge-path-headwater",
};
const FLOW_HOVER_STYLE: PathOptions = { color: "#ffffff", weight: 3, opacity: 0.95 };

const styleFor = (isHeadwater: boolean) =>
  isHeadwater ? HEADWATER_FLOW_STYLE : FLOW_STYLE;

const fmt = (value: number | null, unit: string) =>
  value == null ? "unknown" : `${Number(value).toFixed(1)} ${unit}`;

/** Directed display paths derived from HydroBASINS `NEXT_DOWN` topology. This is
 * a visual scaffold for catchment transport; real river-following paths come from
 * HydroRIVERS/MERIT flowlines in the next hydrologic-map phase. */
export default function FlowEdgeLayer() {
  const selected = useAppStore((s) => s.selected);
  const show = useAppStore((s) => s.showFlowEdges);
  const { data } = useFlowEdges();
  if (!selected || !show || !data) return null;
  const features = data.features.filter((f) => f.properties.reservoir_id === selected);
  if (features.length === 0) return null;
  const collection: GeoFC<FlowEdgeProperties> = { type: "FeatureCollection", features };
  return (
    <GeoJSON
      key={`flow-edges-${selected}`}
      data={collection}
      style={(feature) => styleFor(!!feature?.properties?.is_headwater)}
      onEachFeature={(feature, layer) => {
        const props = feature.properties as FlowEdgeProperties;
        const resting = styleFor(props.is_headwater);
        layer.bindTooltip(
          `HYBAS ${props.from_hybas_id} downstream<br/>distance ${fmt(
            props.distance_to_reservoir_km,
            "km",
          )}<br/>lag proxy ${fmt(props.routing_lag_days, "d")}`,
        );
        layer.once("add", () => {
          const el = (layer as Path).getElement() as SVGPathElement | null;
          if (!el || props.routing_lag_days == null) return;
          el.style.setProperty("--flow-delay", `${Math.min(props.routing_lag_days, 7)}s`);
        });
        layer.on({
          mouseover: (event: LeafletMouseEvent) => {
            (event.target as Path).setStyle(FLOW_HOVER_STYLE);
          },
          mouseout: (event: LeafletMouseEvent) => {
            (event.target as Path).setStyle(resting);
          },
        });
      }}
    />
  );
}
