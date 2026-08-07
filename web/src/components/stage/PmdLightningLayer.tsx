import { CircleMarker, Tooltip } from "react-leaflet";
import { usePmdLightning } from "../../lib/queries";
import { useAppStore } from "../../lib/store";

const MAX_STRIKES = 300;

const fmt = (value: number | null, unit: string) =>
  value == null ? "n/a" : `${Number(value).toFixed(1)} ${unit}`;

export default function PmdLightningLayer() {
  const show = useAppStore((s) => s.showPmdLightning);
  const hours = useAppStore((s) => s.pmdLightningHours);
  const { data } = usePmdLightning(hours, show);
  if (!show || !data?.features.length) return null;

  const stride = Math.max(1, Math.ceil(data.features.length / MAX_STRIKES));
  return (
    <>
      {data.features.map((feature, index) => {
        if (index % stride !== 0 || feature.geometry?.type !== "Point") return null;
        const [lon, lat] = feature.geometry.coordinates;
        if (lon === undefined || lat === undefined) return null;
        const props = feature.properties;
        const negative = props.polarity?.toLowerCase().includes("negative");
        return (
          <CircleMarker
            key={`${props.strike_id ?? index}-${props.strike_time ?? props.fetched_at}`}
            center={[lat, lon]}
            radius={negative ? 4.5 : 3.5}
            pathOptions={{
              color: props.stale ? "#f5a623" : "#f7f7ff",
              fillColor: negative ? "#9b5cff" : "#f7d154",
              fillOpacity: props.stale ? 0.45 : 0.82,
              weight: 1.4,
            }}
          >
            <Tooltip direction="top" offset={[0, -8]}>
              <strong>Lightning strike</strong>
              <br />
              {props.strike_time ?? "time n/a"} · {props.window_hours}h window
              <br />
              {props.polarity ?? "polarity n/a"} · {fmt(props.peak_current_ka, "kA")}
              <br />
              {props.source} · {props.cache_status}
              {props.stale ? " · stale" : ""}
            </Tooltip>
          </CircleMarker>
        );
      })}
    </>
  );
}
