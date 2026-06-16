import { CircleMarker, MapContainer, Popup, TileLayer } from "react-leaflet";

import { RISK_COLOR, type FeatureCollection, type RiskLevel } from "../types";

interface Props {
  features: FeatureCollection | null;
  onSelect: (reservoirId: string) => void;
}

export function ReservoirMap({ features, onSelect }: Props) {
  return (
    <MapContainer center={[31.7, 76.2]} zoom={7} style={{ height: "100%", width: "100%" }}>
      <TileLayer
        attribution="&copy; OpenStreetMap contributors"
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {features?.features.map((f) => {
        if (!f.geometry) return null;
        const [lon, lat] = f.geometry.coordinates;
        const level = (f.properties.risk_level ?? "Low") as RiskLevel;
        return (
          <CircleMarker
            key={f.properties.reservoir_id}
            center={[lat, lon]}
            radius={11}
            pathOptions={{ color: "#333", weight: 1, fillColor: RISK_COLOR[level], fillOpacity: 0.85 }}
            eventHandlers={{ click: () => onSelect(f.properties.reservoir_id) }}
          >
            <Popup>
              <strong>{f.properties.name}</strong>
              <br />
              Risk: {f.properties.risk_level ?? "—"}
            </Popup>
          </CircleMarker>
        );
      })}
    </MapContainer>
  );
}
