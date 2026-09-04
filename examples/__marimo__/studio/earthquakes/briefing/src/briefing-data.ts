export type TemporalValue = Date | string | number | bigint;

export type EventSummary = {
  events: number;
  felt_reports: number;
  maximum_magnitude: number;
  minimum_magnitude: number;
  status: string;
  tsunami_flags: number;
};

export type WeeklySummary = {
  felt_reports: number;
  generated_at: string;
  maximum_magnitude: number;
  period_end: string;
  period_start: string;
  qualified_events: number;
  source_events: number;
  source_title: string;
  source_url: string;
  tsunami_flags: number;
};

export type DailyActivity = {
  day: TemporalValue;
  events: number;
  felt_reports: number;
  maximum_magnitude: number;
  median_magnitude: number;
};

export type EarthquakeEvent = {
  felt: number | null;
  id: string;
  latitude: number;
  longitude: number;
  magnitude: number;
  place: string;
  selected: boolean;
  significance: number;
  status: string;
  time: TemporalValue;
  tsunami: boolean;
  url: string;
};

export type MagnitudeScaling = {
  amplitude_ratio: number;
  difference: number;
  energy_ratio: number;
  maximum_magnitude: number;
  reference_magnitude: number;
};

export type FrequencyPoint = {
  events: number;
  fitted_events: number;
  fitted_log10_events: number;
  log10_events: number;
  magnitude: number;
};

export type FrequencyModel = {
  b_value: number;
  fit_maximum: number;
  fit_minimum: number;
  fit_observations: number;
  intercept: number;
  r_squared: number;
};

export type SeismicAnalysis = {
  activity: DailyActivity[];
  events: EarthquakeEvent[];
  frequency: {
    curve: FrequencyPoint[];
    default_magnitude: number;
    model: FrequencyModel;
  };
  magnitude: {
    comparisons: MagnitudeScaling[];
    default_reference: number;
  };
  strongest: EarthquakeEvent[];
  weekly: WeeklySummary;
};

export type BriefingModel = {
  activity: DailyActivity[];
  analysis?: SeismicAnalysis;
  events: EarthquakeEvent[];
  maximumDailyCount: number;
  maximumDailyMagnitude: number;
  peakActivity?: DailyActivity;
  peakKey?: string;
  primaryEvent?: EarthquakeEvent;
  strongest: EarthquakeEvent[];
};

export type CatalogSelection = {
  events: EarthquakeEvent[];
  summary: EventSummary;
};

export const integer = new Intl.NumberFormat("en-US");

const compact = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 1,
  notation: "compact",
});
const monthDay = new Intl.DateTimeFormat("en", {
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});
const dayOnly = new Intl.DateTimeFormat("en", {
  day: "numeric",
  timeZone: "UTC",
});
const yearOnly = new Intl.DateTimeFormat("en", {
  year: "numeric",
  timeZone: "UTC",
});
const eventTime = new Intl.DateTimeFormat("en", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  timeZone: "UTC",
});

const toDate = (value: TemporalValue) => {
  if (value instanceof Date) return value;
  if (typeof value === "string") return new Date(value);

  const numeric = Number(value);
  const magnitude = Math.abs(numeric);
  if (magnitude > 1e17) return new Date(numeric / 1e6);
  if (magnitude > 1e14) return new Date(numeric / 1e3);
  if (magnitude < 1e11) return new Date(numeric * 1e3);
  return new Date(numeric);
};

export const formatDay = (value: TemporalValue) => {
  const date = toDate(value);
  return Number.isNaN(date.valueOf()) ? String(value) : monthDay.format(date);
};

export const formatTime = (value: TemporalValue) => {
  const date = toDate(value);
  return Number.isNaN(date.valueOf())
    ? String(value)
    : `${eventTime.format(date)} UTC`;
};

export const formatPeriod = (summary?: WeeklySummary) => {
  if (!summary) return "Seven-day record";
  const start = new Date(`${summary.period_start}T00:00:00Z`);
  const end = new Date(`${summary.period_end}T00:00:00Z`);
  if (Number.isNaN(start.valueOf()) || Number.isNaN(end.valueOf())) {
    return "Seven-day record";
  }
  if (start.getUTCFullYear() !== end.getUTCFullYear()) {
    return `${monthDay.format(start)}, ${yearOnly.format(start)}–${
      monthDay.format(end)
    }, ${yearOnly.format(end)}`;
  }
  if (start.getUTCMonth() !== end.getUTCMonth()) {
    return `${monthDay.format(start)}–${monthDay.format(end)}, ${
      yearOnly.format(end)
    }`;
  }
  return `${monthDay.format(start)}–${dayOnly.format(end)}, ${
    yearOnly.format(end)
  }`;
};

export const concisePlace = (place: string) => {
  const marker = " of ";
  const offset = place.lastIndexOf(marker);
  return offset === -1 ? place : place.slice(offset + marker.length);
};

export const feltLabel = (value: number | null) =>
  value === null || value === 0
    ? "No felt reports"
    : `${integer.format(value)} felt reports`;

export const formatRatio = (value: number) =>
  value >= 10_000 ? compact.format(value) : integer.format(Math.round(value));

export const magnitudeScalingAt = (
  values: readonly MagnitudeScaling[],
  reference: number,
) =>
  values.reduce<MagnitudeScaling | undefined>((nearest, value) => {
    if (nearest === undefined) return value;
    return Math.abs(value.reference_magnitude - reference) <
        Math.abs(nearest.reference_magnitude - reference)
      ? value
      : nearest;
  }, undefined);

export const frequencyPointAt = (
  values: readonly FrequencyPoint[],
  magnitude: number,
) =>
  values.reduce<FrequencyPoint | undefined>((nearest, value) => {
    if (nearest === undefined) return value;
    return Math.abs(value.magnitude - magnitude) <
        Math.abs(nearest.magnitude - magnitude)
      ? value
      : nearest;
  }, undefined);

export const selectCatalog = (
  events: readonly EarthquakeEvent[],
  minimumMagnitude: number,
  status: string,
): CatalogSelection => {
  const selected = events.filter((event) =>
    event.magnitude >= minimumMagnitude &&
    (status === "All statuses" || event.status === status)
  );
  const selectedIds = new Set(selected.map((event) => event.id));
  const summary: EventSummary = {
    events: selected.length,
    felt_reports: selected.reduce(
      (total, event) => total + (event.felt ?? 0),
      0,
    ),
    maximum_magnitude: selected.reduce(
      (maximum, event) => Math.max(maximum, event.magnitude),
      0,
    ),
    minimum_magnitude: minimumMagnitude,
    status,
    tsunami_flags: selected.reduce(
      (total, event) => total + Number(event.tsunami),
      0,
    ),
  };
  return {
    events: events.map((event) => ({
      ...event,
      selected: selectedIds.has(event.id),
    })),
    summary,
  };
};

export const createBriefingModel = (
  analysis?: SeismicAnalysis,
): BriefingModel => {
  const activity = analysis?.activity ?? [];
  const events = analysis?.events ?? [];
  const strongest = analysis?.strongest.slice(0, 6) ?? [];
  const peakActivity = activity.length === 0
    ? undefined
    : activity.reduce((peak, row) => row.events > peak.events ? row : peak);

  return {
    activity,
    analysis,
    events,
    maximumDailyCount: Math.max(1, ...activity.map((row) => row.events)),
    maximumDailyMagnitude: Math.max(
      0,
      ...activity.map((row) => row.maximum_magnitude),
    ),
    peakActivity,
    peakKey: peakActivity ? String(peakActivity.day) : undefined,
    primaryEvent: strongest[0],
    strongest,
  };
};
