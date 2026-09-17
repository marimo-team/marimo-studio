import * as Plot from "@observablehq/plot";

export const integer = new Intl.NumberFormat("en");
export const decimal = new Intl.NumberFormat("en", {
  maximumFractionDigits: 1,
});
export const percent = new Intl.NumberFormat("en", {
  style: "percent",
  maximumFractionDigits: 1,
});
export const unitFor = (metric) =>
  ({ CO2: "ppm", Light: "lux", Temperature: "°C", Humidity: "%" })[metric] ??
    "";

const asDate = (value) => {
  if (value instanceof Date) return value;
  if (typeof value === "string") return new Date(value);
  const numeric = Number(value);
  const magnitude = Math.abs(numeric);
  return new Date(
    magnitude > 1e17
      ? numeric / 1e6
      : magnitude > 1e14
      ? numeric / 1e3
      : magnitude < 1e11
      ? numeric * 1e3
      : numeric,
  );
};

export const readingRows = (table) =>
  table.toArray().map((row) => ({ ...row, date: asDate(row.date) }));

const chartWidth = (width) => Math.max(1, Math.min(1080, width));
const style = {
  background: "transparent",
  color: "#55584f",
  fontFamily: "inherit",
  fontSize: "12px",
};

export const historyChart = (rows, metric, width) => {
  const chart = Plot.plot({
    width: chartWidth(width),
    height: width < 600 ? 280 : 370,
    marginLeft: 58,
    marginRight: 20,
    style,
    ariaLabel: `${metric} history with rolling baseline and flagged deviations`,
    x: { type: "utc", label: null, ticks: width < 600 ? 4 : 8 },
    y: { label: `${metric} (${unitFor(metric)})`, grid: true },
    marks: [
      Plot.lineY(rows, {
        x: "date",
        y: "baseline",
        stroke: "#92968c",
        strokeWidth: 1.5,
        strokeDasharray: "4,3",
      }),
      Plot.lineY(rows, {
        x: "date",
        y: "value",
        stroke: "#326453",
        strokeWidth: 1.4,
      }),
      Plot.dot(rows.filter((row) => row.anomaly), {
        x: "date",
        y: "value",
        fill: "#b07739",
        r: 2.5,
      }),
      Plot.crosshair(rows, { x: "date", y: "value", color: "#326453" }),
    ],
  });
  chart.classList.add("sensor-chart");
  chart.setAttribute("data-marimo-lens-inputs", "series-data summary-data");
  return chart;
};

const dayLabel = new Intl.DateTimeFormat("en", {
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});

export const occupancyChart = (rows, width) => {
  const compact = width < 600;
  const chart = Plot.plot({
    width: chartWidth(width),
    height: compact ? Math.max(180, rows.length * 32 + 58) : 230,
    marginLeft: compact ? 54 : 58,
    marginRight: compact ? 46 : 20,
    style,
    ariaLabel: "Daily share of occupied readings",
    x: compact
      ? {
        domain: [0, 1],
        label: null,
        ticks: width < 300 ? [0, 0.5, 1] : [0, 0.25, 0.5, 0.75, 1],
        tickFormat: "%",
        grid: true,
      }
      : {
        type: "band",
        label: null,
        tickFormat: (day) => String(day).slice(5),
      },
    y: compact
      ? {
        type: "band",
        domain: rows.map((row) => row.day),
        label: null,
        tickFormat: (day) => dayLabel.format(asDate(day)),
        tickSize: 0,
      }
      : {
        domain: [0, 1],
        label: "Occupied share",
        tickFormat: "%",
        grid: true,
      },
    marks: compact
      ? [
        Plot.barX(rows, {
          x: "occupancy_rate",
          y: "day",
          fill: "#7c998b",
          insetTop: 4,
          insetBottom: 4,
        }),
        Plot.text(rows, {
          x: "occupancy_rate",
          y: "day",
          text: (row) => percent.format(row.occupancy_rate),
          textAnchor: "start",
          dx: 7,
          fill: "#30352f",
        }),
        Plot.ruleX([0]),
      ]
      : [
        Plot.barY(rows, {
          x: "day",
          y: "occupancy_rate",
          fill: "#7c998b",
          insetLeft: 8,
          insetRight: 8,
          tip: true,
        }),
        Plot.ruleY([0]),
      ],
  });
  chart.classList.add("occupancy-chart");
  chart.setAttribute("data-marimo-lens-inputs", "daily-data");
  return chart;
};
