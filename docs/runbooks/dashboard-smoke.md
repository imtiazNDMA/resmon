# Dashboard smoke pass (manual, ~5 min)

Prereq: `start.bat` (stack up, migrated, backfill loaded via
`uv run python scripts/load_backfill.py`), GEE key present.

1. Load app → sidebar slides in, buttons stagger, map fades from black.
2. Click Gobind Sagar → camera flies in (~1.8 s), timeline dock rises,
   meter fills, latest SAR scene fades onto the map.
3. Scrub the slider → tiles crossfade ~300 ms, meter eases, date ticks,
   number counts (never snaps).
4. Press ▶ → auto-advance ~600 ms/step; press again to pause; let it reach
   the end → playback stops by itself.
5. Switch to Pong mid-play → playback stops, camera flies, dock reloads.
6. Click Dashboard → map view swaps out, panels stagger in with cascade,
   fleet chart draws; rainfall panel shows "awaiting live forcing".
7. Stop the API (`docker compose stop api`) → per-source failures degrade
   (chips/empty states), no blank screen.
8. Remove/rename the GEE key, restart API, pick a date → amber
   "live imagery unavailable" chip; basemap + AOI outline still render.
