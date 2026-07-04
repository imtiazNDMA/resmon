import { useEffect } from "react";
import { CircleMarker, GeoJSON, MapContainer, TileLayer, useMap } from "react-leaflet";
import { useAcquisitions, useAoi, useMarkers } from "../../lib/queries";
import { useAppStore } from "../../lib/store";
import AreaMeter from "./AreaMeter";
import CatchmentLayer from "./CatchmentLayer";
import SarTileLayer from "./SarTileLayer";
import TimelineDock from "./TimelineDock";

const HOME: [number, number] = [31.9, 76.1];

/** Eased camera: flies to the selected reservoir marker (spec motion score). */
function CameraDriver() {
  const map = useMap();
  const selected = useAppStore((s) => s.selected);
  const { data: markers } = useMarkers();
  useEffect(() => {
    if (!selected || !markers) return;
    const f = markers.features.find((x) => x.properties.reservoir_id === selected);
    if (!f || f.geometry?.type !== "Point") return;
    const [lon, lat] = f.geometry.coordinates;
    map.flyTo([lat!, lon!], 11, { duration: 1.8, easeLinearity: 0.18 });
  }, [selected, markers, map]);
  return null;
}

export default function MapView() {
  const selected = useAppStore((s) => s.selected);
  const activeDate = useAppStore((s) => s.activeDate);
  const setActiveDate = useAppStore((s) => s.setActiveDate);
  const { data: aoi } = useAoi();
  const { data: markers } = useMarkers();
  const { data: acqs } = useAcquisitions(selected);

  // default the timeline to the latest acquisition on reservoir switch
  useEffect(() => {
    if (selected && acqs?.length && activeDate === null)
      setActiveDate(acqs[acqs.length - 1]!.date);
  }, [selected, acqs, activeDate, setActiveDate]);

  return (
    <div className="mapview">
      <MapContainer center={HOME} zoom={8} zoomControl={false} className="leaflet-root">
        <TileLayer
          url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
          attribution="Esri"
        />
        <CameraDriver />
        {aoi && (
          <GeoJSON
            key={`aoi-${aoi.features.length}`}
            data={aoi}
            style={{ color: "#59b7ff", weight: 1.5, fillOpacity: 0.05 }}
          />
        )}
        <CatchmentLayer />
        {markers?.features.map((f) => {
          if (f.geometry?.type !== "Point") return null;
          const [lon, lat] = f.geometry.coordinates;
          return (
            <CircleMarker
              key={f.properties.reservoir_id}
              center={[lat!, lon!]}
              radius={8}
              pathOptions={{ color: "#dff0ff", fillColor: "#59b7ff", fillOpacity: 0.9 }}
            />
          );
        })}
        {selected && activeDate && <SarTileLayer rid={selected} date={activeDate} />}
      </MapContainer>
      {selected && acqs && <AreaMeter acquisitions={acqs} />}
      {selected && acqs && <TimelineDock acquisitions={acqs} />}
    </div>
  );
}
