export type EventSummary = {
  events: number;
  felt_reports: number;
  maximum_magnitude: number;
  minimum_magnitude: number;
  status: string;
  tsunami_flags: number;
};

export type WeeklySummary = {
  source_events: number;
  qualified_events: number;
  maximum_magnitude: number;
  felt_reports: number;
  tsunami_flags: number;
  period_start: string;
  period_end: string;
};

export type TemporalValue = Date | string | number | bigint;

export type DailyActivity = {
  day: TemporalValue;
  events: number;
  maximum_magnitude: number;
};

export type StrongEvent = {
  felt: number | null;
  id: string;
  latitude: number;
  longitude: number;
  magnitude: number;
  place: string;
  time: TemporalValue;
  tsunami: boolean;
};

export type BriefingModel = {
  activity: DailyActivity[];
  maximumDailyCount: number;
  maximumDailyMagnitude: number;
  peakActivity?: DailyActivity;
  peakKey?: string;
  primaryEvent?: StrongEvent;
  strongest: StrongEvent[];
  summary?: EventSummary;
  weekly?: WeeklySummary;
};

export const integer = new Intl.NumberFormat("en-US");

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
  value === null ? "No felt reports" : `${integer.format(value)} felt reports`;

export const createBriefingModel = ({
  activity,
  strongest,
  summary,
  weekly,
}: {
  activity: DailyActivity[];
  strongest: StrongEvent[];
  summary?: EventSummary;
  weekly?: WeeklySummary;
}): BriefingModel => {
  const peakActivity = activity.length === 0
    ? undefined
    : activity.reduce((peak, row) => row.events > peak.events ? row : peak);

  return {
    activity,
    maximumDailyCount: Math.max(1, ...activity.map((row) => row.events)),
    maximumDailyMagnitude: Math.max(
      0,
      ...activity.map((row) => row.maximum_magnitude),
    ),
    peakActivity,
    peakKey: peakActivity ? String(peakActivity.day) : undefined,
    primaryEvent: strongest[0],
    strongest,
    summary,
    weekly,
  };
};
