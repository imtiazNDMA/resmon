import { GeoJSON } from "react-leaflet";
import type { Layer, PathOptions } from "leaflet";
import { usePmdMonsoon, usePmdWarnings } from "../../lib/queries";
import { useAppStore } from "../../lib/store";
import type { PmdMonsoonProperties, PmdWarningProperties } from "../../types";

const severityColor = (severity: string | null) => {
  const value = severity?.toLowerCase() ?? "";
  if (value.includes("severe") || value.includes("warning") || value.includes("red")) return "#ff4d4d";
  if (value.includes("watch") || value.includes("orange")) return "#ff9f1c";
  if (value.includes("yellow") || value.includes("advisory")) return "#f7d154";
  return "#b8e6ff";
};

const styleFor = (severity: string | null): PathOptions => {
  const color = severityColor(severity);
  return { color, weight: 2, opacity: 0.95, fillColor: color, fillOpacity: 0.16 };
};

const escapeHtml = (value: string | null | undefined) =>
  String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

function bindWarningTooltip(layer: Layer, props: PmdWarningProperties) {
  layer.bindTooltip(
    `<strong>${escapeHtml(props.hazard ?? "PMD warning")}</strong><br/>${escapeHtml(props.severity ?? "severity n/a")}<br/>${escapeHtml(props.area_name ?? "area n/a")}<br/>${escapeHtml(props.source_timestamp ?? "time n/a")} · ${escapeHtml(props.cache_status)}${props.stale ? " · stale" : ""}<br/>${escapeHtml(props.source)}`,
  );
}

function bindMonsoonTooltip(layer: Layer, props: PmdMonsoonProperties) {
  layer.bindTooltip(
    `<strong>${escapeHtml(props.data_type ?? "Monsoon warning")}</strong><br/>${escapeHtml(props.severity ?? "severity n/a")}<br/>${escapeHtml(props.source_timestamp ?? "time n/a")} · ${escapeHtml(props.cache_status)}${props.stale ? " · stale" : ""}<br/>${escapeHtml(props.source)}`,
  );
}

export default function PmdWarningLayer() {
  const showWarnings = useAppStore((s) => s.showPmdWarnings);
  const showMonsoon = useAppStore((s) => s.showPmdMonsoon);
  const warnings = usePmdWarnings(showWarnings);
  const monsoon = usePmdMonsoon(showMonsoon);

  return (
    <>
      {showWarnings && warnings.data && (
        <GeoJSON
          key={`pmd-warnings-${warnings.data.features.length}`}
          data={warnings.data}
          style={(feature) => styleFor((feature?.properties as PmdWarningProperties).severity)}
          onEachFeature={(feature, layer) =>
            bindWarningTooltip(layer, feature.properties as PmdWarningProperties)
          }
        />
      )}
      {showMonsoon && monsoon.data && (
        <GeoJSON
          key={`pmd-monsoon-${monsoon.data.features.length}`}
          data={monsoon.data}
          style={(feature) => styleFor((feature?.properties as PmdMonsoonProperties).severity)}
          onEachFeature={(feature, layer) =>
            bindMonsoonTooltip(layer, feature.properties as PmdMonsoonProperties)
          }
        />
      )}
    </>
  );
}
