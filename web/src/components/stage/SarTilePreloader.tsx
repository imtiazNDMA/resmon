import L from "leaflet";
import { useEffect } from "react";
import { useMap } from "react-leaflet";
import { useQueryClient } from "@tanstack/react-query";
import { sarTileQuery } from "../../lib/queries";
import { useAppStore, type ReservoirId } from "../../lib/store";

export default function SarTilePreloader(props: { rid: ReservoirId; dates: string[] }) {
  const map = useMap();
  const queryClient = useQueryClient();
  const composite = useAppStore((s) => s.sarComposite);

  useEffect(() => {
    if (props.dates.length === 0) return;
    const layers: L.TileLayer[] = [];
    const timeouts: number[] = [];
    let cancelled = false;

    for (const date of props.dates) {
      void queryClient.fetchQuery(sarTileQuery(props.rid, date, composite)).then((tile) => {
        if (cancelled || !tile?.tile_url) return;
        const layer = L.tileLayer(tile.tile_url, {
          opacity: 0,
          maxZoom: 14,
          pane: "overlayPane",
          updateWhenIdle: false,
          keepBuffer: 2,
        });
        layers.push(layer);
        layer.addTo(map);
        const remove = () => {
          if (map.hasLayer(layer)) map.removeLayer(layer);
        };
        layer.once("load", remove);
        timeouts.push(window.setTimeout(remove, 8000));
      }).catch(() => undefined);
    }

    return () => {
      cancelled = true;
      for (const timeout of timeouts) window.clearTimeout(timeout);
      for (const layer of layers) {
        if (map.hasLayer(layer)) map.removeLayer(layer);
      }
    };
  }, [props.dates, props.rid, composite, map, queryClient]);

  return null;
}
