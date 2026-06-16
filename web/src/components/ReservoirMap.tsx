import { CircleMarker, GeoJSON, LayersControl, MapContainer, Popup, TileLayer } from "react-leaflet";

import { RISK_COLOR, type FeatureCollection, type GeoFC, type RiskLevel } from "../types";

const { BaseLayer, Overlay } = LayersControl;

interface Props {
  markers: FeatureCollection | null;
  aoi: GeoFC | null;
  catchment: GeoFC | null;
  water: GeoFC | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function ReservoirMap({ markers, aoi, catchment, water, selectedId, onSelect }: Props) {
  return (
    <div className="map-wrap">
      <MapContainer center={[31.9, 76.0]} zoom={8} style={{ height: "100%", width: "100%" }}>
        <LayersControl position="topright">
          <BaseLayer checked name="Satellite">
            <TileLayer
              attribution="Tiles &copy; Esri — Source: Esri, Maxar, Earthstar Geographics"
              url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
            />
          </BaseLayer>
          <BaseLayer name="Street">
            <TileLayer
              attribution="&copy; OpenStreetMap contributors"
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
          </BaseLayer>

          {catchment && (
            <Overlay name="Catchment (HydroBASINS)">
              <GeoJSON
                data={catchment}
                style={() => ({ color: "#f59e0b", weight: 1.5, fillOpacity: 0.05, dashArray: "5 5" })}
              />
            </Overlay>
          )}
          {aoi && (
            <Overlay checked name="Reservoir AOI (JRC GSW)">
              <GeoJSON data={aoi} style={() => ({ color: "#38bdf8", weight: 2, fillOpacity: 0.08 })} />
            </Overlay>
          )}
          {water && (
            <Overlay checked name="Water extent (Sentinel-1)">
              <GeoJSON
                data={water}
                style={() => ({ color: "#0ea5e9", weight: 1, fillColor: "#22d3ee", fillOpacity: 0.55 })}
              />
            </Overlay>
          )}
        </LayersControl>

        {markers?.features.map((f) => {
          if (!f.geometry) return null;
          const [lon, lat] = f.geometry.coordinates;
          const p = f.properties;
          const level = (p.risk_level ?? "Low") as RiskLevel;
          const isSel = p.reservoir_id === selectedId;
          return (
            <CircleMarker
              key={p.reservoir_id}
              center={[lat, lon]}
              radius={isSel ? 13 : 9}
              pathOptions={{
                color: isSel ? "#ffffff" : "#0b1b2b",
                weight: isSel ? 3 : 1.5,
                fillColor: RISK_COLOR[level],
                fillOpacity: 0.95,
              }}
              eventHandlers={{ click: () => onSelect(p.reservoir_id) }}
            >
              <Popup>
                <strong>{p.name}</strong>
                <br />
                Release risk: {p.risk_level ?? "—"}
              </Popup>
            </CircleMarker>
          );
        })}
      </MapContainer>

      <div className="legend">
        <div className="legend-title">Release risk</div>
        {(["Low", "Watch", "Warning", "Imminent"] as RiskLevel[]).map((l) => (
          <div key={l} className="legend-row">
            <span className="legend-swatch" style={{ background: RISK_COLOR[l] }} />
            {l}
          </div>
        ))}
        <div className="legend-sep" />
        <div className="legend-row">
          <span className="legend-swatch" style={{ background: "#22d3ee" }} />
          Water extent (SAR)
        </div>
        <div className="legend-row">
          <span className="legend-swatch outline-blue" />
          Reservoir AOI
        </div>
        <div className="legend-row">
          <span className="legend-swatch outline-amber" />
          Catchment
        </div>
      </div>
    </div>
  );
}
