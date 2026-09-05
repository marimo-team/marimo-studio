<script lang="ts">
import { LineChart, ScatterChart } from "echarts/charts";
import {
  AriaComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from "echarts/components";
import { type ECharts, init, use } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { onMount } from "svelte";

import { type MarimoTable, observeMarimoValue } from "./lib/marimo-value.ts";

type SensorRow = {
  date: Date | string | number | bigint;
  Occupancy: number;
  metric: string;
  value: number;
  baseline: number | null;
  anomaly: boolean;
};

type OccupancySummary = {
  room: string;
  scope_label: string;
  observations: number;
  occupied: number;
  occupancy_rate: number;
  reading_interval_minutes: number;
  estimated_occupied_hours: number;
  metric: string;
  anomalies: number;
  monitor: {
    anomaly_quantile: number;
    anomaly_window: number;
    baseline_window: number;
  };
};

type DailyRoomRow = {
  day: string;
  observations: number;
  occupancy_rate: number;
  mean_co2: number;
  peak_co2: number;
  mean_temperature: number;
};

use([
  AriaComponent,
  CanvasRenderer,
  GridComponent,
  LegendComponent,
  LineChart,
  ScatterChart,
  TooltipComponent,
]);

let chartElement: HTMLDivElement;
let chart: ECharts | undefined;
let chartFrame: number | undefined;
let series = $state.raw<MarimoTable<SensorRow> | undefined>();
let summary = $state<OccupancySummary | undefined>();
let daily = $state.raw<MarimoTable<DailyRoomRow> | undefined>();
let latest = $state<SensorRow | undefined>();
let seriesError = $state(false);
let summaryError = $state(false);
let dailyError = $state(false);
let dailyRows = $derived(daily?.toArray() ?? []);
let loading = $derived(
  !seriesError && !summaryError && !dailyError &&
    (series === undefined || summary === undefined || daily === undefined),
);

const formatNumber = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 1,
});
const formatInteger = new Intl.NumberFormat();
const formatTime = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "UTC",
});
const formatDay = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
});

const formatPercentile = (quantile: number) => {
  const percentile = Math.round(quantile * 100);
  const remainder = percentile % 100;
  const suffixes: Record<number, string> = { 1: "st", 2: "nd", 3: "rd" };
  const suffix = remainder >= 11 && remainder <= 13
    ? "th"
    : suffixes[percentile % 10] ?? "th";
  return `${percentile}${suffix}`;
};

const unitFor = (metric: string) =>
  ({ CO2: "ppm", Light: "lx", Temperature: "°C", Humidity: "%" })[
    metric
  ] ?? "";

const toMilliseconds = (value: SensorRow["date"]): number => {
  if (value instanceof Date) return value.getTime();
  if (typeof value === "string") return Date.parse(value);

  const numeric = Number(value);
  const magnitude = Math.abs(numeric);
  if (magnitude > 1e17) return numeric / 1e6;
  if (magnitude > 1e14) return numeric / 1e3;
  if (magnitude < 1e11) return numeric * 1e3;
  return numeric;
};

const renderChart = () => {
  if (chart === undefined || series === undefined) return;
  chart.resize();

  const rows = series.toArray();
  const metric = summary?.metric ?? rows.at(-1)?.metric ?? "Signal";
  const unit = unitFor(metric);
  const values = rows.map((row) => [toMilliseconds(row.date), row.value]);
  const baseline = rows.map((row) => [
    toMilliseconds(row.date),
    row.baseline,
  ]);
  const anomalies = rows
    .filter((row) => row.anomaly)
    .map((row) => [toMilliseconds(row.date), row.value]);

  chart.setOption(
    {
      animationDuration: matchMedia("(prefers-reduced-motion: reduce)").matches
        ? 0
        : 240,
      useUTC: true,
      aria: { enabled: true },
      color: ["#1c3a13", "#8a9385", "#546b43"],
      grid: { left: 18, right: 18, top: 48, bottom: 28, containLabel: true },
      legend: {
        top: 4,
        left: 0,
        itemWidth: 18,
        itemHeight: 3,
        textStyle: {
          color: "#687164",
          fontFamily: "IBM Plex Mono",
          fontSize: 11,
        },
      },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "line" },
        valueFormatter: (value: unknown) => {
          const reading = Array.isArray(value) ? value.at(-1) : value;
          return reading === null || reading === undefined
            ? "…"
            : `${formatNumber.format(Number(reading))}${
              unit ? ` ${unit}` : ""
            }`;
        },
      },
      xAxis: {
        type: "time",
        boundaryGap: false,
        axisLine: { lineStyle: { color: "#c4c7c4" } },
        axisTick: { show: false },
        axisLabel: {
          color: "#687164",
          fontFamily: "IBM Plex Mono",
          hideOverlap: true,
        },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        name: unit,
        nameTextStyle: {
          color: "#687164",
          fontFamily: "IBM Plex Mono",
          align: "right",
        },
        axisLabel: { color: "#687164", fontFamily: "IBM Plex Mono" },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { lineStyle: { color: "#dedfda" } },
        scale: true,
      },
      series: [
        {
          name: metric,
          type: "line",
          data: values,
          showSymbol: false,
          sampling: "lttb",
          lineStyle: { width: 1.7 },
          emphasis: { disabled: true },
        },
        {
          name: summary
            ? `${summary.monitor.baseline_window}-reading baseline`
            : "Rolling baseline",
          type: "line",
          data: baseline,
          showSymbol: false,
          connectNulls: true,
          lineStyle: { width: 1.3, type: "dashed" },
          emphasis: { disabled: true },
        },
        {
          name: "Anomaly",
          type: "scatter",
          data: anomalies,
          symbolSize: 7,
          itemStyle: {
            color: "#546b43",
            borderColor: "#ffffff",
            borderWidth: 1,
          },
        },
      ],
    },
    true,
  );
};

const scheduleChart = () => {
  if (chartFrame !== undefined) cancelAnimationFrame(chartFrame);
  chartFrame = requestAnimationFrame(() => {
    chartFrame = undefined;
    renderChart();
  });
};

onMount(() => {
  chart = init(chartElement, undefined, { renderer: "canvas" });
  const resize = new ResizeObserver(() => chart?.resize());
  resize.observe(chartElement);
  renderChart();

  return () => {
    if (chartFrame !== undefined) cancelAnimationFrame(chartFrame);
    resize.disconnect();
    chart?.dispose();
    chart = undefined;
  };
});
</script>

<span
  aria-hidden="true"
  hidden
  mo-value="selected_sensor_series"
  use:observeMarimoValue={{
    selector: "selected_sensor_series",
    onValue: (value: MarimoTable<SensorRow>) => {
      series = value;
      latest = value.numRows === 0
        ? undefined
        : (value.get(value.numRows - 1) ?? undefined);
      seriesError = false;
      scheduleChart();
    },
    onError: () => {
      seriesError = true;
      chart?.clear();
    },
  }}
></span>

<span
  aria-hidden="true"
  hidden
  mo-value="occupancy_summary"
  use:observeMarimoValue={{
    selector: "occupancy_summary",
    onValue: (value: OccupancySummary) => {
      summary = value;
      summaryError = false;
      scheduleChart();
    },
    onError: () => {
      summaryError = true;
    },
  }}
></span>

<span
  aria-hidden="true"
  hidden
  mo-value="daily_room_profile"
  use:observeMarimoValue={{
    selector: "daily_room_profile",
    onValue: (value: MarimoTable<DailyRoomRow>) => {
      daily = value;
      dailyError = false;
    },
    onError: () => {
      dailyError = true;
    },
  }}
></span>

<main class="monitor-shell" class:is-loading={loading} aria-busy={loading}>
  <header class="monitor-header">
    <div>
      <p class="eyebrow">Facilities · {summary?.room ?? "Room"}</p>
      <h1>Environmental monitor</h1>
      <p class="lede">
        {summary?.room ?? "Room"} sensor history with a
        {summary ? `${summary.monitor.baseline_window}-reading` : "rolling"}
        baseline and flagged deviations.
      </p>
    </div>
    <div
      class="status"
      aria-label="Dataset status"
      aria-live="polite"
      role="status"
    >
      <span class="status-dot"></span>
      <span>{summary?.scope_label ?? "Historical telemetry"}</span>
      {#if summary}
        <strong>{formatInteger.format(summary.observations)} readings</strong>
      {/if}
    </div>
  </header>

  <section class="control-bar" aria-labelledby="signal-heading">
    <div>
      <p class="section-label" id="signal-heading">Analysis controls</p>
      <p>Choose an observation scope and room signal.</p>
    </div>
    <div class="control-bar-controls">
      <marimo-cell name="analysis_scope_control"></marimo-cell>
      <marimo-cell name="metric_control"></marimo-cell>
    </div>
  </section>

  <section class="metrics" aria-label="Occupancy monitor summary">
    <article>
      <span>Selected signal</span>
      <strong>{summary?.metric ?? latest?.metric ?? "Loading"}</strong>
      <small>
        {unitFor(summary?.metric ?? latest?.metric ?? "") || "Physical measure"}
      </small>
    </article>
    <article>
      <span>Latest reading</span>
      <strong>{latest ? formatNumber.format(latest.value) : "…"}</strong>
      <small>
        {latest
          ? `${unitFor(latest.metric)} · ${formatTime.format(new Date(toMilliseconds(latest.date)))}`
          : "Waiting for sensor data"}
      </small>
    </article>
    <article>
      <span>Occupied observations</span>
      <strong>
        {summary ? `${(summary.occupancy_rate * 100).toFixed(1)}%` : "…"}
      </strong>
      <small>
        {summary
          ? `${formatInteger.format(summary.occupied)} recorded · ${formatNumber.format(summary.estimated_occupied_hours)} h estimated`
          : "Calculating rate"}
      </small>
    </article>
    <article class:attention={summary !== undefined && summary.anomalies > 0}>
      <span>Anomaly candidates</span>
      <strong>{summary ? formatInteger.format(summary.anomalies) : "…"}</strong>
      <small>
        {summary
          ? summary.anomalies
            ? "Marked on the trend"
            : "No candidates detected"
          : "Reviewing signal"}
      </small>
    </article>
  </section>

  <section class="daily-profile" aria-labelledby="daily-heading">
    <div class="daily-heading">
      <div>
        <p class="section-label">Room use profile</p>
        <h2 id="daily-heading">Daily occupancy</h2>
      </div>
      <p>Share of recorded minutes marked occupied</p>
    </div>
    <div class="daily-strip">
      {#each dailyRows as day (day.day)}
        <article>
          <div>
            <span>{formatDay.format(new Date(`${day.day}T00:00:00`))}</span>
            <strong>{(day.occupancy_rate * 100).toFixed(0)}%</strong>
          </div>
          <span class="daily-track" aria-hidden="true">
            <i style={`width: ${day.occupancy_rate * 100}%`}></i>
          </span>
          <small>{formatNumber.format(day.mean_co2)} ppm mean CO₂</small>
        </article>
      {/each}
    </div>
    {#if dailyError}
      <p class="summary-error" role="alert">Daily room use is unavailable.</p>
    {/if}
  </section>

  <section class="chart-panel" aria-labelledby="trend-heading">
    <div class="chart-heading">
      <div>
        <p class="section-label">Sensor history</p>
        <h2 id="trend-heading">Reading and rolling baseline</h2>
      </div>
      <p>
        Baseline window:
        {summary ? `${summary.monitor.baseline_window} observations` : "…"}
      </p>
    </div>
    <div
      class="chart"
      bind:this={chartElement}
      role="img"
      aria-label={`${summary?.metric ?? "Selected sensor"} readings with rolling baseline and anomaly markers`}
    ></div>
    {#if seriesError}
      <p class="chart-state" role="alert">Sensor history is unavailable.</p>
    {:else if series === undefined}
      <p class="chart-state chart-state-loading" aria-live="polite">
        <span class="monitor-loader" aria-hidden="true"><i></i><i></i><i></i></span>
        Loading sensor history…
      </p>
    {/if}
  </section>

  {#if summaryError}
    <p class="summary-error" role="alert">
      Summary metrics are unavailable. Sensor history remains available.
    </p>
  {/if}

  <footer>
    <span>
      Source: <a href="https://doi.org/10.24432/C5X01N" target="_blank" rel="noreferrer">
        Luis Candanedo, UCI Occupancy Detection training split
      </a>
      · <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noreferrer">CC BY 4.0</a>
    </span>
    {#if summary}
      <span>
        Anomalies exceed the rolling
        {formatPercentile(summary.monitor.anomaly_quantile)}-percentile
        deviation limit over {summary.monitor.anomaly_window} observations.
      </span>
    {/if}
  </footer>
</main>
