import { usePmdPredictions } from "../../lib/queries";
import { useAppStore } from "../../lib/store";

interface ForecastLayerProps {
  elementKey: string;
  label: string;
}

export default function PmdForecastLayer({ elementKey, label }: ForecastLayerProps) {
  const show = useAppStore(
    (s) =>
      (elementKey === "pmd_pred_hourtpe" && s.showPmdPredHourly) ||
      (elementKey === "pmd_pred_sixtpe" && s.showPmdPredSix) ||
      (elementKey === "pmd_pred_twelvetpe" && s.showPmdPredTwelve) ||
      (elementKey === "pmd_pred_daytpe" && s.showPmdPredDay),
  );
  const { data } = usePmdPredictions(elementKey, show);

  if (!show || !data?.available) return null;

  // Forecast layers are currently metadata-only pending raster PNG conversion.
  // This component renders the available forecast metadata.
  // When raster images become available (after 8C.5 validation), this can be updated
  // to render the actual prediction rasters as overlays with appropriate opacity/styling.

  return (
    <div
      style={{
        position: "absolute",
        bottom: "10px",
        right: "10px",
        background: "rgba(255, 255, 255, 0.9)",
        padding: "8px",
        borderRadius: "4px",
        fontSize: "12px",
        maxWidth: "280px",
        zIndex: 400,
      }}
    >
      <strong>{label}</strong>
      <div style={{ fontSize: "11px", color: "#666", marginTop: "4px" }}>
        {data.run && <div>Model run: {data.run}</div>}
        <div>Frames: {data.steps.length}</div>
        <div style={{ fontSize: "10px", color: "#999", marginTop: "4px" }}>
          {data.metadata_status} · {data.cache_status}
        </div>
      </div>
    </div>
  );
}
