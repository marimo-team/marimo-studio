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

// One family carries every role. Display text sets its own weight and tracking.
export const typefaces = {
  body: "Inter",
  display: "Inter",
} as const;

// Inter vertical metrics in em. React PDF places the baseline one
// ascent below the top of a text box, whatever its line height, so these
// metrics position glyphs exactly against marks, rings, and fills.
export const fontMetrics = { ascent: 0.96875, capHeight: 0.7275 } as const;

/** Distance from the top of a text box to the vertical center of its capitals. */
export const capCenter = (fontSize: number) =>
  (fontMetrics.ascent - fontMetrics.capHeight / 2) * fontSize;

/** Distance from the top of a text box to the top of its capitals. */
export const capTop = (fontSize: number) =>
  (fontMetrics.ascent - fontMetrics.capHeight) * fontSize;

/** Top offset that centers a line of capitals within a box of `height`. */
export const capInset = (fontSize: number, height: number) =>
  height / 2 - capCenter(fontSize);

/** Space between the baseline and the bottom of a text box. */
export const baselineGap = (fontSize: number, lineHeight: number) =>
  fontSize * (lineHeight - fontMetrics.ascent);

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
