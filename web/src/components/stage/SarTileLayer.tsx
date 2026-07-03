import gsap from "gsap";
import L from "leaflet";
import { useEffect, useRef } from "react";
import { useMap } from "react-leaflet";
import { useSarTile } from "../../lib/queries";
import type { ReservoirId } from "../../lib/store";

/** Crossfading Sentinel-1 tile pair: on each date change the new layer fades in
 *  over the old one, then the old layer is removed (spec: scrub crossfade 300ms). */
export default function SarTileLayer(props: { rid: ReservoirId; date: string | null }) {
  const map = useMap();
  const currentRef = useRef<L.TileLayer | null>(null);
  const { data, error } = useSarTile(props.rid, props.date);

  useEffect(() => {
    if (!data?.tile_url) return;
    const next = L.tileLayer(data.tile_url, { opacity: 0, maxZoom: 14, pane: "overlayPane" });
    next.addTo(map);
    const prev = currentRef.current;
    currentRef.current = next;
    const state = { o: 0 };
    const tween = gsap.to(state, {
      o: 0.85,
      duration: 0.3,
      ease: "power1.inOut",
      onUpdate: () => next.setOpacity(state.o),
      onComplete: () => {
        if (prev) map.removeLayer(prev);
      },
    });
    return () => {
      tween.kill();
    };
  }, [data?.tile_url, map]);

  useEffect(
    () => () => {
      // unmount: drop any live layer
      if (currentRef.current) map.removeLayer(currentRef.current);
    },
    [map],
  );

  if (error) return <div className="imagery-chip">⚠ live imagery unavailable</div>;
  return null;
}
