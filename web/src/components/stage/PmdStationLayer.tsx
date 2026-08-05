import { CircleMarker, Tooltip } from "react-leaflet";
import { usePmdStations } from "../../lib/queries";
import { useAppStore } from "../../lib/store";

const MAX_MARKERS = 180;

const fmt = (value: number | null, unit: string) =>
  value == null ? "n/a" : `${Number(value).toFixed(1)} ${unit}`;

/** PMD station observations are a national context layer; keep markers capped until clustering lands. */
export default function PmdStationLayer() {
  const show = useAppStore((s) => s.showPmdStations);
  const { data } = usePmdStations(show);
  if (!show || !data?.features.length) return null;

  const stride = Math.max(1, Math.ceil(data.features.length / MAX_MARKERS));
  return (
    <>
      {data.features.map((feature, index) => {
        if (index % stride !== 0 || feature.geometry?.type !== "Point") return null;
        const [lon, lat] = feature.geometry.coordinates;
        if (lon === undefined || lat === undefined) return null;
        const props = feature.properties;
        const hot = props.warn_rain || props.warn_wind || props.warn_temp || props.warn_vis;
        return (
          <CircleMarker
            key={`${props.station_id ?? props.code ?? index}-${props.fetched_at}`}
            center={[lat, lon]}
            radius={hot ? 6 : 4}
            pathOptions={{
              color: props.stale ? "#f5a623" : hot ? "#ff5252" : "#d9fff8",
              fillColor: hot ? "#ff5252" : "#1ec8b5",
              fillOpacity: props.stale ? 0.45 : 0.75,
              weight: hot ? 2 : 1,
            }}
          >
            <Tooltip direction="top" offset={[0, -8]}>
              <strong>{props.name ?? props.code ?? "PMD station"}</strong>
              <br />
              {fmt(props.temperature_c, "C")} · rain 24h {fmt(props.rain_24h_mm, "mm")}
              <br />
              {props.source_timestamp ?? "time n/a"} · {props.cache_status}
              {props.stale ? " · stale" : ""}
              <br />
              {props.source}
            </Tooltip>
          </CircleMarker>
        );
      })}
    </>
  );
}
