import { GeoJSON } from "react-leaflet";
import { useDistricts } from "../../lib/queries";
import { useAppStore } from "../../lib/store";

/** Administrative district outlines. Drawn with no fill so the satellite imagery
 *  remains readable while the downstream administrative context is visible. */
export default function DistrictBoundaryLayer() {
  const show = useAppStore((s) => s.showDistricts);
  const { data } = useDistricts();
  if (!show || !data) return null;
  return (
    <GeoJSON
      key={`districts-${data.features.length}`}
      data={data}
      style={{ color: "#ffffff", weight: 1.2, opacity: 0.9, fillOpacity: 0 }}
    />
  );
}
