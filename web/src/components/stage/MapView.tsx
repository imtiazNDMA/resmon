import { useEffect, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { CircleMarker, GeoJSON, MapContainer, TileLayer, useMap } from "react-leaflet";
import { sarTileQuery, useAcquisitions, useAoi, useMarkers } from "../../lib/queries";
import { useAppStore } from "../../lib/store";
import AreaMeter from "./AreaMeter";
import CatchmentLayer from "./CatchmentLayer";
import LayerChips from "./LayerChips";
import SarTileLayer from "./SarTileLayer";
import TimelineDock from "./TimelineDock";
import WaterExtentLayer from "./WaterExtentLayer";

const HOME: [number, number] = [31.9, 76.1];

function MapSizeInvalidator() {
  const map = useMap();

  useEffect(() => {
    const container = map.getContainer();
    const invalidate = () => map.invalidateSize({ animate: false });
    const animationFrame = requestAnimationFrame(invalidate);
    const timeout = window.setTimeout(invalidate, 500);
    const observer = new ResizeObserver(invalidate);

    observer.observe(container);
    window.addEventListener("load", invalidate);
    window.addEventListener("resize", invalidate);

    return () => {
      cancelAnimationFrame(animationFrame);
      window.clearTimeout(timeout);
      observer.disconnect();
      window.removeEventListener("load", invalidate);
      window.removeEventListener("resize", invalidate);
    };
  }, [map]);

  return null;
}

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
    if (lon === undefined || lat === undefined) return;
    map.flyTo([lat!, lon!], 11, { duration: 1.8, easeLinearity: 0.18 });
  }, [selected, markers, map]);
  return null;
}

export default function MapView() {
  const queryClient = useQueryClient();
  const selected = useAppStore((s) => s.selected);
  const activeDate = useAppStore((s) => s.activeDate);
  const imageryDateFrom = useAppStore((s) => s.imageryDateFrom);
  const imageryDateTo = useAppStore((s) => s.imageryDateTo);
  const setActiveDate = useAppStore((s) => s.setActiveDate);
  const { data: aoi } = useAoi();
  const { data: markers } = useMarkers();
  const { data: acqs } = useAcquisitions(selected);
  const filteredAcqs = useMemo(
    () =>
      acqs?.filter(
        (a) =>
          (!imageryDateFrom || a.date >= imageryDateFrom) && (!imageryDateTo || a.date <= imageryDateTo),
      ),
    [acqs, imageryDateFrom, imageryDateTo],
  );

  // Default to the latest acquisition in the selected date range.
  useEffect(() => {
    if (!selected || !filteredAcqs) return;
    if (filteredAcqs.length === 0) {
      if (activeDate !== null) setActiveDate(null);
      return;
    }
    if (activeDate === null || !filteredAcqs.some((a) => a.date === activeDate))
      setActiveDate(filteredAcqs[filteredAcqs.length - 1]!.date);
  }, [selected, filteredAcqs, activeDate, setActiveDate]);

  useEffect(() => {
    if (!selected || !activeDate || !filteredAcqs?.length) return;
    const idx = filteredAcqs.findIndex((a) => a.date === activeDate);
    if (idx < 0) return;
    for (const neighbor of [filteredAcqs[idx - 1], filteredAcqs[idx + 1]]) {
      if (neighbor) void queryClient.prefetchQuery(sarTileQuery(selected, neighbor.date));
    }
  }, [selected, activeDate, filteredAcqs, queryClient]);

  return (
    <div className="mapview">
      <MapContainer center={HOME} zoom={8} zoomControl={false} className="leaflet-root">
        <MapSizeInvalidator />
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
        <WaterExtentLayer />
        {markers?.features.map((f) => {
          if (f.geometry?.type !== "Point") return null;
          const [lon, lat] = f.geometry.coordinates;
          if (lon === undefined || lat === undefined) return null;
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
      <LayerChips />
      {selected && filteredAcqs && filteredAcqs.length > 0 && <AreaMeter acquisitions={filteredAcqs} />}
      {selected && filteredAcqs && filteredAcqs.length > 0 && (
        <TimelineDock acquisitions={filteredAcqs} />
      )}
      {selected && filteredAcqs && filteredAcqs.length === 0 && (
        <div className="empty-range-chip">No imagery in selected date range</div>
      )}
    </div>
  );
}
