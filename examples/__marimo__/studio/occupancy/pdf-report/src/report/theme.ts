export const palette = {
  ink: "#102126",
  slate: "#3d5761",
  fog: "#677b82",
  paper: "#ffffff",
  mist: "#f1f7f9",
  rule: "#e9eef0",
  orange: "#fa4e1d",
  coral: "#fb6338",
  orangeWash: "#fff0ea",
  sky: "#e4eeff",
} as const;

export const typefaces = {
  body: "Hanken Grotesk",
  display: "Newsreader",
} as const;

const compactNumber = new Intl.NumberFormat("en", {
  notation: "compact",
  maximumFractionDigits: 1,
});
const dayLabel = new Intl.DateTimeFormat("en", {
  month: "short",
  day: "numeric",
});
const periodLabel = new Intl.DateTimeFormat("en", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export const formatPercent = (value: number, digits = 1) =>
  `${(value * 100).toFixed(digits)}%`;

export const formatCompact = (value: number) => compactNumber.format(value);

export const formatMeasure = (value: number, unit: string) => {
  const digits = unit === "°C" ? 1 : 0;
  return `${value.toFixed(digits)} ${unit}`;
};

export const formatDay = (value: string) =>
  dayLabel.format(new Date(`${value}T00:00:00`));

export const formatPeriod = (start: string, end: string) => {
  return `${periodLabel.format(new Date(start))} – ${
    periodLabel.format(new Date(end))
  }`;
};

export const formatTimestamp = (value: Date | string | number | bigint) => {
  if (value instanceof Date) {
    return value.toISOString().slice(0, 16).replace("T", " ");
  }
  if (typeof value === "string") {
    return value.slice(0, 16).replace("T", " ");
  }

  const numeric = Number(value);
  const magnitude = Math.abs(numeric);
  const milliseconds = magnitude > 1e17
    ? numeric / 1e6
    : magnitude > 1e14
    ? numeric / 1e3
    : magnitude < 1e11
    ? numeric * 1e3
    : numeric;
  return new Date(milliseconds).toISOString().slice(0, 16).replace("T", " ");
};
