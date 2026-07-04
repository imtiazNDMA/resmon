/** Scrub/staleness rules for the water-extent overlay, kept pure so the
 *  date-string contracts are testable without mounting Leaflet. */

const DAY_MS = 86_400_000;

/** Mirrors `data_staleness_threshold_days` (core/src/core/config.py, NFR-REL-6/D8). */
export const STALENESS_THRESHOLD_DAYS = 14;

// Data dates live on the IST calendar (D9) — age must not use the browser's zone.
const IST_DATE = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" });

/** YYYY-MM-DD "today" on the IST calendar. */
export function istToday(): string {
  return IST_DATE.format(new Date());
}

function toUtcMs(isoDate: string): number {
  return Date.parse(`${isoDate.slice(0, 10)}T00:00:00Z`);
}

/** The extent polygon may only show when the timeline sits on the latest
 *  acquisition — scrubbed back, the outline would contradict older imagery. */
export function isExtentVisible(
  activeDate: string | null,
  latestAcquisitionDate: string | null | undefined,
): boolean {
  if (!activeDate || !latestAcquisitionDate) return false;
  return activeDate.slice(0, 10) === latestAcquisitionDate.slice(0, 10);
}

export function extentAgeDays(acquisitionDate: string, today: string = istToday()): number {
  return Math.round((toUtcMs(today) - toUtcMs(acquisitionDate)) / DAY_MS);
}

export function isExtentStale(acquisitionDate: string, today: string = istToday()): boolean {
  return extentAgeDays(acquisitionDate, today) > STALENESS_THRESHOLD_DAYS;
}

/** "2026-06-12" -> "12 Jun" for the extent date chip. */
export function formatDayMonth(isoDate: string): string {
  return new Date(toUtcMs(isoDate)).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}
