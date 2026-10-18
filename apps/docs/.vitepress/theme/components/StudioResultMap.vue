<script setup lang="ts">
import { computed, ref, useId } from "vue";

import StudioCode from "./StudioCode.vue";
import { useWideFigure } from "./wide-figure.ts";

type Kind = "cell" | "output" | "value";
type Region = "North" | "South";

// Orders per quarter. The figure recomputes every result from this table, the
// way the notebook would, so the dropdown drives both panes.
const orders: Record<Region, readonly number[]> = {
  North: [118, 131, 146, 139],
  South: [94, 108, 101, 127],
};

const region = ref<Region>("North");
const kind = ref<Kind>("cell");
const total = computed(() => orders[region.value].reduce((sum, count) => sum + count, 0));
const bars = computed(() => orders[region.value]);
const id = useId();
const figure = ref<HTMLElement>();
const wide = useWideFigure(figure);

// Each cell names the line that defines what the page places, so the figure
// can point at it.
const cells = [
  {
    kind: "cell",
    name: "region_control",
    code: 'region = mo.ui.dropdown(\n    ["North", "South"],\n    value="North",\n    label="Region",\n)\nregion',
    line: 5,
  },
  {
    kind: "output",
    name: "quarterly_section",
    code: 'quarterly_chart = plot_quarters(\n    orders, region.value\n)\nmo.vstack([\n    mo.md("### Orders per quarter"),\n    quarterly_chart,\n    mo.md("Source: order log"),\n])',
    line: 0,
  },
  {
    kind: "value",
    name: "summary",
    code: 'rows = orders[\n    orders["region"] == region.value\n]\nsummary = {"orders": len(rows)}',
    line: 3,
  },
] as const;

const source = [
  '<main id="app-shell">',
  "  <h1>Regional orders</h1>",
  '  <marimo-cell name="region_control"></marimo-cell>',
  '  <marimo-output value="quarterly_chart"></marimo-output>',
  '  <p>Orders: <strong mo-value="summary.orders"></strong></p>',
  "</main>",
].join("\n");
const sourceLine: Record<Kind, number> = { cell: 2, output: 3, value: 4 };

const kinds: Record<Kind, { label: string; host: string; receives: string }> = {
  cell: {
    label: "Cell",
    host: '<marimo-cell name="region_control">',
    receives:
      "Everything the cell shows, as marimo renders it, here the live dropdown. Both panes show one control, so picking a region in either reruns the cells that read it.",
  },
  output: {
    label: "Output",
    host: '<marimo-output value="quarterly_chart">',
    receives:
      'The rich representation of one variable. The cell `quarterly_section` shows a stack with a heading and a caption, and the page takes only the figure in `quarterly_chart`. `<marimo-cell name="quarterly_section">` would place the whole stack.',
  },
  value: {
    label: "Value",
    host: 'mo-value="summary.orders"',
    receives:
      "Data as JSON. Text, a number, or a boolean appears in the element as text, and page code can read any value, such as a record or a table, from the element's `marimoValue` property.",
  },
};
const order: readonly Kind[] = ["cell", "output", "value"];

// Backticks in an explanation mark code, without a Markdown renderer.
const segments = (text: string): { text: string; code: boolean }[] =>
  text
    .split(/(`[^`]+`)/)
    .filter(Boolean)
    .map((part) =>
      part.startsWith("`") ? { text: part.slice(1, -1), code: true } : { text: part, code: false },
    );
</script>

<template>
  <figure
    ref="figure"
    class="studio-figure-block studio-result-map"
    :style="wide"
    :aria-labelledby="`${id}-caption`"
  >
    <div class="studio-choice" role="group" aria-label="Kind of notebook result">
      <button
        v-for="item in order"
        :key="item"
        type="button"
        :aria-pressed="kind === item"
        @click="kind = item"
      >
        {{ kinds[item].label }}
      </button>
    </div>

    <div class="studio-result-map__panes">
      <section class="studio-card is-notebook" aria-label="Notebook analysis.py">
        <header class="studio-card__header"><span>Notebook</span><span>analysis.py</span></header>
        <div class="studio-card__body studio-result-map__cells">
          <article
            v-for="cell in cells"
            :key="cell.name"
            class="studio-cell studio-result-map__cell"
            :data-linked="kind === cell.kind || undefined"
            @mouseenter="kind = cell.kind"
            @focusin="kind = cell.kind"
          >
            <StudioCode
              :code="cell.code"
              language="python"
              line-numbers
              :active="kind === cell.kind ? [cell.line] : []"
            />
            <div v-if="cell.kind === 'cell'" class="studio-cell__output">
              <label class="studio-result-map__control">
                Region
                <select v-model="region">
                  <option>North</option>
                  <option>South</option>
                </select>
              </label>
            </div>
            <div v-else-if="cell.kind === 'output'" class="studio-cell__output is-stack">
              <p class="studio-result-map__md-heading">Orders per quarter</p>
              <div
                class="studio-result-map__variable"
                :data-linked="kind === 'output' || undefined"
                data-name="quarterly_chart"
              >
                <svg
                  class="studio-result-map__chart"
                  viewBox="0 0 240 96"
                  role="img"
                  :aria-label="`Orders per quarter in the ${region} region: ${bars.join(', ')}`"
                >
                  <g v-for="(count, quarter) in bars" :key="quarter">
                    <rect
                      :x="18 + quarter * 56"
                      :y="78 - count / 2.6"
                      width="36"
                      :height="count / 2.6"
                      rx="2"
                    />
                    <text :x="36 + quarter * 56" y="92" text-anchor="middle">
                      Q{{ quarter + 1 }}
                    </text>
                  </g>
                </svg>
              </div>
              <p class="studio-result-map__md-caption">Source: order log</p>
            </div>
            <div class="studio-cell__footer">
              <span class="studio-cell__name">{{ cell.name }}</span>
            </div>
          </article>
        </div>
      </section>

      <section class="studio-card" aria-label="View dashboard">
        <header class="studio-card__header">
          <span>HTML page</span><span>dashboard/index.html</span>
        </header>
        <div class="studio-result-map__page">
          <p class="studio-result-map__heading">Regional orders</p>
          <div
            class="studio-result-map__host"
            data-host="marimo-cell"
            :data-linked="kind === 'cell' || undefined"
            @mouseenter="kind = 'cell'"
            @focusin="kind = 'cell'"
          >
            <label class="studio-result-map__control">
              Region
              <select v-model="region">
                <option>North</option>
                <option>South</option>
              </select>
            </label>
          </div>
          <div
            class="studio-result-map__host"
            data-host="marimo-output"
            :data-linked="kind === 'output' || undefined"
            @mouseenter="kind = 'output'"
            @focusin="kind = 'output'"
          >
            <svg class="studio-result-map__chart" viewBox="0 0 240 96" aria-hidden="true">
              <g v-for="(count, quarter) in bars" :key="quarter">
                <rect
                  :x="18 + quarter * 56"
                  :y="78 - count / 2.6"
                  width="36"
                  :height="count / 2.6"
                  rx="2"
                />
                <text :x="36 + quarter * 56" y="92" text-anchor="middle">Q{{ quarter + 1 }}</text>
              </g>
            </svg>
          </div>
          <p class="studio-result-map__metric">
            Orders:
            <strong
              class="studio-result-map__host is-inline"
              data-host="mo-value"
              :data-linked="kind === 'value' || undefined"
              @mouseenter="kind = 'value'"
              @focusin="kind = 'value'"
              >{{ total }}</strong
            >
          </p>
        </div>
        <div class="studio-result-map__source">
          <StudioCode :code="source" language="html" :active="[sourceLine[kind]]" />
        </div>
      </section>
    </div>

    <div class="studio-note studio-result-map__note" aria-live="polite">
      <p class="studio-result-map__host-line">
        <code>{{ kinds[kind].host }}</code>
        <span v-if="kind === 'value'">JSON {{ total }}</span>
      </p>
      <p>
        <template v-for="(part, index) in segments(kinds[kind].receives)" :key="index">
          <code v-if="part.code">{{ part.text }}</code>
          <template v-else>{{ part.text }}</template>
        </template>
      </p>
    </div>

    <figcaption :id="`${id}-caption`">
      <slot>
        A notebook and a view that places three of its results. Choose a kind of result, or point at
        a cell or a host, to see what connects them.
      </slot>
    </figcaption>
  </figure>
</template>

<style scoped>
.studio-result-map__panes {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 1.25rem;
  align-items: start;
}

@container (max-width: 540px) {
  .studio-result-map__panes {
    grid-template-columns: minmax(0, 1fr);
  }
}

.studio-result-map__cells {
  display: grid;
  gap: 10px;
}

.studio-result-map__cell {
  transition:
    border-color 0.2s ease,
    box-shadow 0.2s ease;
}

.studio-result-map__cell[data-linked] {
  border-color: var(--studio-link);
}

.studio-result-map__cell[data-linked] .studio-cell__name {
  color: var(--studio-link);
}

.studio-result-map__cell :deep(.studio-code) {
  padding-block: 10px;
}

.studio-cell__output.is-stack {
  display: grid;
  gap: 6px;
}

.studio-result-map__control {
  display: inline-flex;
  gap: 8px;
  align-items: center;
  color: var(--vp-c-text-1);
  font-size: 13px;
}

.studio-result-map__control select {
  padding: 2px 24px 2px 8px;
  border: 1px solid var(--studio-card-border);
  border-radius: 6px;
  background: var(--studio-card-bg)
    url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M1 1l4 4 4-4' fill='none' stroke='%23889' stroke-width='1.4'/%3E%3C/svg%3E")
    no-repeat right 8px center;
  color: inherit;
  font: inherit;
  appearance: none;
  cursor: pointer;
}

.studio-result-map__md-heading {
  margin: 0;
  color: var(--vp-c-text-1);
  font-size: 15px;
  font-weight: 600;
  line-height: 1.4;
}

.studio-result-map__md-caption {
  margin: 0;
  color: var(--vp-c-text-2);
  font-size: 12px;
  line-height: 1.4;
}

.studio-result-map__chart {
  display: block;
  width: 100%;
  max-width: 260px;
  height: auto;
}

.studio-result-map__chart rect {
  fill: var(--studio-chart);
}

.studio-result-map__chart text {
  fill: var(--vp-c-text-2);
  font-size: 10px;
}

.studio-result-map__page {
  display: grid;
  gap: 10px;
  padding: 16px 18px 18px;
}

.studio-result-map__heading {
  margin: 0;
  color: var(--vp-c-text-1);
  font-size: 17px;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.studio-result-map__metric {
  margin: 0;
  color: var(--vp-c-text-1);
  font-size: 14px;
}

/* A host shows a dashed frame and its tag while the figure points at it, and
   the variable that a <marimo-output> takes is framed inside its cell. */
.studio-result-map__host,
.studio-result-map__variable {
  position: relative;
  border-radius: 6px;
  outline: 1px dashed transparent;
  outline-offset: 2px;
  transition:
    outline-color 0.2s ease,
    background-color 0.2s ease;
}

.studio-result-map__host {
  padding: 6px;
}

.studio-result-map__host.is-inline {
  padding: 1px 4px;
}

.studio-result-map__host[data-linked],
.studio-result-map__variable[data-linked] {
  outline-color: var(--studio-link);
}

.studio-result-map__host[data-linked] {
  background: var(--studio-link-soft);
}

.studio-result-map__host[data-linked]::after,
.studio-result-map__variable[data-linked]::after {
  position: absolute;
  top: -18px;
  right: 0;
  padding: 0 5px;
  border-radius: 3px;
  background: var(--studio-link);
  color: var(--vp-c-bg);
  font-family: var(--vp-font-family-mono);
  font-size: 10px;
  font-weight: 500;
  line-height: 15px;
  white-space: nowrap;
}

.studio-result-map__host[data-linked]::after {
  content: "<" attr(data-host) ">";
}

.studio-result-map__host.is-inline[data-linked]::after {
  content: "mo-value";
}

.studio-result-map__variable[data-linked]::after {
  content: attr(data-name);
}

.studio-result-map__source {
  border-top: 1px solid var(--studio-chrome-rule);
}

.studio-result-map__source :deep(.studio-code) {
  padding-block: 10px;
}

.studio-result-map__note p {
  margin: 0;
}

.studio-result-map__note p + p {
  margin-top: 4px;
  color: var(--vp-c-text-2);
}

.studio-result-map__host-line {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  align-items: baseline;
}

.studio-result-map__host-line span {
  color: var(--vp-c-text-2);
  font-family: var(--vp-font-family-mono);
  font-size: 12px;
}
</style>
