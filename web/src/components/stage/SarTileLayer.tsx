import gsap from "gsap";
import L from "leaflet";
import { useEffect, useRef } from "react";
import { useMap } from "react-leaflet";
import { useSarTile } from "../../lib/queries";
import { useAppStore, type ReservoirId } from "../../lib/store";

/** Crossfading Sentinel-1 tile pair: on each date change the new layer fades in
 *  over the old one, then the old layer is removed (spec: scrub crossfade 300ms). */
export default function SarTileLayer(props: { rid: ReservoirId; date: string | null }) {
  const map = useMap();
  const composite = useAppStore((s) => s.sarComposite);
  const currentRef = useRef<L.TileLayer | null>(null);
  const { data, error } = useSarTile(props.rid, props.date, composite);

  useEffect(() => {
    if (!data?.tile_url) return;
    const next = L.tileLayer(data.tile_url, {
      opacity: 0.18,
      maxZoom: 14,
      pane: "overlayPane",
      updateWhenIdle: false,
      keepBuffer: 3,
    });
    next.addTo(map);
    const prev = currentRef.current;
    currentRef.current = next;
    let loaded = false;
    const state = { o: 0 };
    const tween = gsap.to(state, {
      o: 0.85,
      duration: 0.65,
      ease: "power1.inOut",
      paused: true,
      onUpdate: () => {
        if (map.hasLayer(next)) next.setOpacity(state.o);
        if (prev && map.hasLayer(prev)) prev.setOpacity(0.85 - state.o);
      },
      onComplete: () => {
        if (prev && map.hasLayer(prev)) map.removeLayer(prev);
      },
    });
    const startFade = () => {
      if (loaded) return;
      loaded = true;
      tween.play();
    };
    next.once("tileload", startFade);
    next.once("load", startFade);
    const fallback = window.setTimeout(() => {
      if (!loaded) startFade();
    }, 250);
    return () => {
      window.clearTimeout(fallback);
      next.off("tileload", startFade);
      next.off("load", startFade);
      tween.kill();
      if (map.hasLayer(next)) next.setOpacity(0.85);
      if (prev && map.hasLayer(prev)) map.removeLayer(prev);
    };
  }, [data?.tile_url, map]);

  useEffect(
    () => () => {
      // unmount: drop any live layer
      if (currentRef.current && map.hasLayer(currentRef.current)) map.removeLayer(currentRef.current);
    },
    [map],
  );

  if (error) return <div className="imagery-chip" role="status">live imagery unavailable</div>;
  return null;
}
