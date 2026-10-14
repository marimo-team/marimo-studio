// Draw the bulletin's figures from the notebook's `seismic_analysis` value.
import * as Plot from "https://cdn.jsdelivr.net/npm/@observablehq/plot@0.6.17/+esm";
import { feature } from "https://cdn.jsdelivr.net/npm/topojson-client@3.1.0/+esm";

const ink = "#171716";
const muted = "#64615b";
const line = "#d9dcd7";
const magma = "#b45435";
const sulfur = "#dc8c46";
const font = "IBM Plex Sans, system-ui, sans-serif";

const landRequest = fetch("https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/land-110m.json")
  .then((response) => response.json())
  .then((topology) => feature(topology, topology.objects.land));

const number = new Intl.NumberFormat("en");
const magnitude = (value) => `M${Number(value).toFixed(1)}`;
const utc = new Intl.DateTimeFormat("en", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  timeZone: "UTC",
});
const day = new Intl.DateTimeFormat("en", {
  weekday: "short",
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});

const style = { fontFamily: font, fontSize: "11px", color: ink, background: "transparent", overflow: "visible" };

const replace = (target, chart) => {
  target.replaceChildren(chart);
};

const fillFigures = ({ weekly }) => {
  const values = {
    events: number.format(weekly.source_events),
    maximum: magnitude(weekly.maximum_magnitude),
    felt: number.format(weekly.felt_reports),
    tsunami: number.format(weekly.tsunami_flags),
  };
  for (const [key, text] of Object.entries(values)) {
    const target = document.querySelector(`[data-figure="${key}"]`);
    if (target) target.textContent = text;
  }
};

const drawMap = async (target, events) => {
  const land = await landRequest;
  const width = target.clientWidth;
  replace(
    target,
    Plot.plot({
      width,
      height: Math.round(width * 0.5),
      style,
      projection: { type: "equal-earth", inset: 4 },
      r: { type: "sqrt", domain: [2.5, 7.5], range: [1.2, 13] },
      marks: [
        Plot.sphere({ fill: "#f2f1ec", stroke: line }),
        Plot.graticule({ stroke: line, strokeOpacity: 0.7 }),
        Plot.geo(land, { fill: "#e3e1d9", stroke: "#c9c6bf", strokeWidth: 0.5 }),
        Plot.dot(events, {
          x: "longitude",
          y: "latitude",
          r: "magnitude",
          fill: magma,
          fillOpacity: 0.42,
          stroke: (row) => (row.magnitude >= 6 ? magma : "none"),
          strokeWidth: 1.2,
          sort: { channel: "r", order: "descending" },
          channels: { Place: "place", Magnitude: (row) => magnitude(row.magnitude), Status: "status" },
          tip: { fontFamily: font },
        }),
      ],
    }),
  );
};

const weekday = new Intl.DateTimeFormat("en", { weekday: "short", timeZone: "UTC" });
const dayOfMonth = new Intl.DateTimeFormat("en", { day: "numeric", timeZone: "UTC" });

const drawDays = (target, activity) => {
  const rows = activity.map((row) => ({ ...row, date: new Date(`${row.day}T00:00:00Z`) }));
  const width = target.clientWidth;
  // Narrow figures stack the weekday over the day of the month.
  const tickFormat = width < 560 ? (value) => `${weekday.format(value)}\n${dayOfMonth.format(value)}` : (value) => day.format(value);
  replace(
    target,
    Plot.plot({
      width,
      height: 230,
      style,
      marginTop: 26,
      marginBottom: width < 560 ? 38 : 30,
      x: { type: "band", label: null, tickFormat, padding: 0.28 },
      y: { label: "Events", grid: true, nice: true },
      marks: [
        Plot.barY(rows, { x: "date", y: "events", fill: sulfur, fillOpacity: 0.85 }),
        Plot.text(rows, {
          x: "date",
          y: "events",
          text: (row) => magnitude(row.maximum_magnitude),
          dy: -9,
          fill: magma,
          fontWeight: 600,
        }),
        Plot.ruleY([0], { stroke: ink }),
      ],
    }),
  );
};

const drawGutenberg = (target, frequency) => {
  const { curve, model } = frequency;
  const fitted = curve.filter((row) => row.magnitude >= model.fit_minimum && row.magnitude <= model.fit_maximum);
  replace(
    target,
    Plot.plot({
      width: target.clientWidth,
      height: 280,
      style,
      x: { label: "Magnitude m", nice: true },
      y: { type: "log", label: "Events with M ≥ m", grid: true, ticks: [1, 3, 10, 30, 100, 300], tickFormat: "~s" },
      marks: [
        Plot.rectX([model], { x1: "fit_minimum", x2: "fit_maximum", fill: "#f2f1ec" }),
        Plot.line(fitted, { x: "magnitude", y: "fitted_events", stroke: magma, strokeWidth: 1.6 }),
        Plot.dot(curve, { x: "magnitude", y: "events", r: 2.6, fill: ink, tip: { fontFamily: font } }),
        Plot.text([model], {
          x: "fit_maximum",
          y: (row) => 10 ** (row.intercept - row.b_value * row.fit_maximum),
          text: (row) => `b = ${row.b_value.toFixed(2)} · R² = ${row.r_squared.toFixed(2)}`,
          dx: 8,
          textAnchor: "start",
          fill: magma,
          fontWeight: 600,
        }),
      ],
    }),
  );
};

const fillStrongest = (strongest) => {
  const body = document.querySelector("#strongest-table tbody");
  if (!body) return;
  body.replaceChildren(
    ...strongest.slice(0, 8).map((row) => {
      const tr = document.createElement("tr");
      const cells = [magnitude(row.magnitude), row.place, utc.format(new Date(row.time)), row.felt === null ? "—" : number.format(row.felt)];
      cells.forEach((text, index) => {
        const td = document.createElement("td");
        if (index === 1 && row.url?.startsWith("https://earthquake.usgs.gov/")) {
          const link = document.createElement("a");
          link.href = row.url;
          link.textContent = text;
          link.rel = "noopener";
          td.append(link);
        } else {
          td.textContent = text;
        }
        if (index === 0) td.className = row.magnitude >= 6 ? "magnitude strong" : "magnitude";
        tr.append(td);
      });
      return tr;
    }),
  );
};

// Each figure reads its own notebook value, so a static export stores the
// event table once as Arrow and the summaries as small JSON values.
const latest = {};
const renderers = {
  weekly: (weekly) => fillFigures({ weekly }),
  strongest: (strongest) => fillStrongest(strongest),
  activity: (activity) => drawDays(document.querySelector("#days-chart"), activity),
  frequency: (frequency) => drawGutenberg(document.querySelector("#gutenberg-chart"), frequency),
  events: (events) =>
    drawMap(document.querySelector("#map-chart"), events).catch(() => {
      document.querySelector("#map-chart").textContent = "The world map could not load.";
    }),
};

// Charts wait for a laid-out container. The resize observer renders them again
// once the figure column has its width.
const render = (name) => {
  if (latest[name] === undefined) return;
  if (document.querySelector("#days-chart").clientWidth < 160) return;
  renderers[name](latest[name]);
};
const renderAll = () => Object.keys(renderers).forEach(render);

for (const host of document.querySelectorAll("[data-source]")) {
  const name = host.dataset.source;
  const update = (value) => {
    latest[name] = name === "events" ? value.toArray() : value;
    render(name);
  };
  host.addEventListener("marimo-value-updated", (event) => update(event.detail.value));
  if (host.marimoValue !== undefined) update(host.marimoValue);
}

let width = 0;
new ResizeObserver(([entry]) => {
  const next = Math.round(entry.contentRect.width);
  if (next !== width) {
    width = next;
    renderAll();
  }
}).observe(document.querySelector("#days-chart"));
