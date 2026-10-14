export interface EarthquakeEvent {
  id: string;
  magnitude: number;
  place: string;
  time: Date | string | number | bigint;
  felt: number | null;
  status: string;
  tsunami: boolean;
  significance: number;
  url: string;
  longitude: number;
  latitude: number;
}

export interface EventSummary {
  events: number;
  maximum_magnitude: number;
  felt_reports: number;
  tsunami_flags: number;
  minimum_magnitude: number;
  priority_count: number;
  priority_magnitude: number;
  status: string;
}

const INTEGER_FORMAT = new Intl.NumberFormat("en-US");
const TIME_FORMAT = new Intl.DateTimeFormat("en-US", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "UTC",
});

export const formatInteger = (value: number | null | undefined): string =>
  value === null || value === undefined ? "…" : INTEGER_FORMAT.format(value);

export const formatMagnitude = (value: number | null | undefined): string =>
  value === null || value === undefined ? "…" : value.toFixed(1);

export const formatEventTime = (value: EarthquakeEvent["time"]): string => {
  const numeric = typeof value === "bigint" ? Number(value) : value;
  const magnitude = typeof numeric === "number" ? Math.abs(numeric) : 0;
  const milliseconds = typeof numeric !== "number"
    ? numeric
    : magnitude > 1e17
    ? numeric / 1e6
    : magnitude > 1e14
    ? numeric / 1e3
    : magnitude < 1e11
    ? numeric * 1e3
    : numeric;
  const parsed = value instanceof Date ? value : new Date(milliseconds);
  return Number.isNaN(parsed.valueOf())
    ? String(value)
    : `${TIME_FORMAT.format(parsed)} UTC`;
};

export const rankEvents = (
  events: readonly EarthquakeEvent[],
  limit: number,
): EarthquakeEvent[] =>
  events
    .toSorted(
      (left, right) =>
        right.magnitude - left.magnitude ||
        right.significance - left.significance,
    )
    .slice(0, limit);
