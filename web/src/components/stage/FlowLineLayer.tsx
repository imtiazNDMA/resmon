import { useState } from "react";
import { GeoJSON } from "react-leaflet";
import type { LeafletMouseEvent, Path, PathOptions } from "leaflet";
import { useMapEvents } from "react-leaflet";
import { useFlowlines } from "../../lib/queries";
import { useAppStore } from "../../lib/store";
import type { FlowlineProperties } from "../../types";

const MAIN_STEM = "#001eff";
const TRIBUTARY = "#003cff";
const HOVER_STYLE: PathOptions = { color: "#ffffff", weight: 4.5, opacity: 0.98 };

const widthFor = (props: FlowlineProperties) => {
  if (props.stream_order != null) return Math.min(5, 1 + props.stream_order * 0.75);
  if (props.upstream_area_km2 != null) return Math.min(5, 1 + Math.log10(props.upstream_area_km2 + 1));
  return 1.4;
};

const styleFor = (props: FlowlineProperties): PathOptions => ({
  color: props.is_main_stem ? MAIN_STEM : TRIBUTARY,
  weight: widthFor(props) + (props.is_main_stem ? 0.55 : 0.15),
  opacity: props.is_main_stem ? 0.98 : 0.88,
  lineCap: "round",
  lineJoin: "round",
  className: props.is_main_stem ? "flowline-path flowline-main" : "flowline-path",
});

const fmt = (value: number | null, unit: string) =>
  value == null ? "unknown" : `${Number(value).toFixed(1)} ${unit}`;

const minOrderForZoom = (zoom: number) => {
  if (zoom < 9) return 4;
  if (zoom < 11) return 2;
  return 1;
};

/** Real HydroRIVERS drainage-network vectors clipped to the selected catchment. */
export default function FlowLineLayer() {
  const selected = useAppStore((s) => s.selected);
  const show = useAppStore((s) => s.showFlowEdges);
  const map = useMapEvents({
    zoomend: () => setMinOrder(minOrderForZoom(map.getZoom())),
  });
  const [minOrder, setMinOrder] = useState(() => minOrderForZoom(map.getZoom()));
  const { data } = useFlowlines(selected, minOrder);
  if (!selected || !show || !data || data.features.length === 0) return null;

  return (
    <GeoJSON
      key={`flowlines-${selected}-${minOrder}-${data.features.length}`}
      data={data}
      style={(feature) => styleFor(feature?.properties as FlowlineProperties)}
      onEachFeature={(feature, layer) => {
        const props = feature.properties as FlowlineProperties;
        const resting = styleFor(props);
        layer.bindTooltip(
          `${props.is_main_stem ? "Main stem" : "Drainage line"} ${props.flowline_id}<br/>order ${props.stream_order ?? "unknown"}<br/>upstream area ${fmt(
            props.upstream_area_km2,
            "km2",
          )}<br/>length ${fmt(props.length_km, "km")}`,
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
