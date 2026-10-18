<script setup lang="ts">
import { computed, ref, useId } from "vue";

import { useWideFigure } from "./wide-figure.ts";

type Surface = "page" | "pdf";
type TargetId = "heading" | "control" | "metric" | "chart" | "sentence" | "figure" | "cell";

interface Target {
  surface: Surface;
  kind: string;
  label: string;
  /** The notebook cell that computed the target, then its upstream cells. */
  cells: readonly string[];
  selector?: string;
  /** Where the view places the target: a host's markup or a source line. */
  placement: string;
  notebook: string;
  view: string;
}

const weekly = [42, 51, 47, 63, 58, 71, 66, 74];
const quarters = [118, 131, 146, 139];
const week = ref(5);
const row = ref(2);

const targets = computed<Record<TargetId, Target>>(() => ({
  heading: {
    surface: "page",
    kind: "Authored region",
    label: "Regional orders",
    cells: [],
    placement: "<h1> inside #app-shell, in index.html",
    notebook: "Nothing. The heading reads no notebook result.",
    view: "The wording, in index.html.",
  },
  control: {
    surface: "page",
    kind: "Placed cell",
    label: "region_control",
    cells: ["region_control"],
    placement: '<marimo-cell name="region_control">',
    notebook: "The dropdown's options and default, in cell region_control.",
    view: "Where the control sits, in index.html.",
  },
  metric: {
    surface: "page",
    kind: "Value",
    label: "summary.orders",
    cells: ["summary", "region_control", "orders"],
    selector: "summary.orders",
    placement: '<strong mo-value="summary.orders">',
    notebook: "How summary counts orders.",
    view: "The label and number format, in index.html.",
  },
  chart: {
    surface: "page",
    kind: "Chart drawn by page code",
    label: "Weekly orders",
    cells: ["weekly_orders", "region_control", "orders"],
    selector: "weekly",
    placement: '<section data-marimo-lens-inputs="weekly-data">',
    notebook: "The weekly counts, in cell weekly_orders.",
    view: "The drawing code, in index.html.",
  },
  sentence: {
    surface: "pdf",
    kind: "Region in a rendered file",
    label: "Total orders",
    cells: ["summary", "region_control", "orders"],
    selector: "summary.orders",
    placement: "main.typ:18, page 1 of main.pdf",
    notebook: "How summary counts orders.",
    view: "The sentence around the number, at main.typ:18.",
  },
  figure: {
    surface: "pdf",
    kind: "Region in a rendered file",
    label: "quarterly_chart",
    cells: ["quarterly_section", "region_control", "orders"],
    selector: "quarterly_chart",
    placement: "main.typ:24, page 1 of main.pdf",
    notebook: "The figure itself, in cell quarterly_section.",
    view: "Its width and caption, at main.typ:24.",
  },
  cell: {
    surface: "pdf",
    kind: "Region in a rendered file",
    label: `Q${row.value + 1} orders`,
    cells: ["report", "orders"],
    selector: `report.rows[${row.value}].orders`,
    placement: "main.typ:41, page 1 of main.pdf",
    notebook: "The rows, in cell report.",
    view: "The table layout, at main.typ:41.",
  },
}));

const surface = ref<Surface>("page");
const selected = ref<Record<Surface, TargetId>>({ page: "metric", pdf: "figure" });
const current = computed(() => targets.value[selected.value[surface.value]]);
const pick = (target: TargetId): void => {
  selected.value[surface.value] = target;
};
const isPicked = (target: TargetId): boolean => selected.value[surface.value] === target;
const chip = (target: TargetId): string => {
  const entry = targets.value[target];
  const [cell] = entry.cells;
  return cell && cell !== entry.label ? `${entry.label} · ${cell}` : entry.label;
};

const surfaces: readonly { key: Surface; label: string }[] = [
  { key: "page", label: "Dashboard · HTML page" },
  { key: "pdf", label: "Report · Typst PDF" },
];
const id = useId();
const figure = ref<HTMLElement>();
const wide = useWideFigure(figure);
</script>

<template>
  <figure
    ref="figure"
    class="studio-figure-block studio-lens-trace"
    :style="wide"
    :aria-labelledby="`${id}-caption`"
  >
    <div class="studio-choice" role="group" aria-label="View">
      <button
        v-for="item in surfaces"
        :key="item.key"
        type="button"
        :aria-pressed="surface === item.key"
        @click="surface = item.key"
      >
        {{ item.label }}
      </button>
    </div>

    <div class="studio-lens-trace__body">
      <section class="studio-card" aria-label="Preview with Lens selecting">
        <header class="studio-card__header">
          <span>Preview</span>
          <span class="studio-lens-trace__mode"><i aria-hidden="true" />Lens · Select</span>
        </header>

        <div v-if="surface === 'page'" class="studio-lens-trace__page">
          <button
            type="button"
            class="studio-lens-trace__target is-heading"
            :aria-pressed="isPicked('heading')"
            :data-chip="chip('heading')"
            @click="pick('heading')"
          >
            Regional orders
          </button>
          <div class="studio-lens-trace__row">
            <button
              type="button"
              class="studio-lens-trace__target"
              :aria-pressed="isPicked('control')"
              :data-chip="chip('control')"
              @click="pick('control')"
            >
              <span class="studio-lens-trace__select">Region <b>North</b></span>
            </button>
            <button
              type="button"
              class="studio-lens-trace__target is-metric is-end"
              :aria-pressed="isPicked('metric')"
              :data-chip="chip('metric')"
              @click="pick('metric')"
            >
              <small>Orders</small><strong>534</strong>
            </button>
          </div>
          <button
            type="button"
            class="studio-lens-trace__target is-chart"
            :aria-pressed="isPicked('chart')"
            :data-chip="chip('chart')"
            :aria-label="`Weekly orders chart, point on week ${week + 1}`"
            @click="pick('chart')"
          >
            <small>Weekly orders</small>
            <svg viewBox="0 0 256 64" aria-hidden="true">
              <rect
                v-for="(count, index) in weekly"
                :key="index"
                :x="4 + index * 32"
                :y="62 - count * 0.8"
                width="22"
                :height="count * 0.8"
                rx="2"
                :data-marked="(isPicked('chart') && index === week) || undefined"
                @click="week = index"
              />
            </svg>
          </button>
        </div>

        <div v-else class="studio-card__viewer studio-lens-trace__paper">
          <div class="studio-lens-trace__sheet">
            <p class="studio-lens-trace__paper-title">Quarterly report</p>
            <p class="studio-lens-trace__prose">
              The North region placed
              <button
                type="button"
                class="studio-lens-trace__target is-inline"
                :aria-pressed="isPicked('sentence')"
                :data-chip="chip('sentence')"
                @click="pick('sentence')"
              >
                534 orders
              </button>
              this year, with the strongest quarter in summer.
            </p>
            <button
              type="button"
              class="studio-lens-trace__target is-figure"
              :aria-pressed="isPicked('figure')"
              :data-chip="chip('figure')"
              @click="pick('figure')"
            >
              <svg viewBox="0 0 240 80" aria-hidden="true">
                <rect
                  v-for="(count, index) in quarters"
                  :key="index"
                  :x="20 + index * 56"
                  :y="70 - count / 2.4"
                  width="34"
                  :height="count / 2.4"
                />
                <line x1="8" x2="232" y1="70.5" y2="70.5" />
              </svg>
              <small>Figure 1. Orders per quarter.</small>
            </button>
            <table>
              <tbody>
                <tr v-for="(count, index) in quarters" :key="index">
                  <th scope="row">Q{{ index + 1 }}</th>
                  <td>
                    <button
                      type="button"
                      class="studio-lens-trace__target is-inline is-end"
                      :aria-pressed="isPicked('cell') && row === index"
                      :data-chip="`report.rows[${index}].orders · report`"
                      @click="
                        row = index;
                        pick('cell');
                      "
                    >
                      {{ count }}
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section class="studio-card studio-lens-trace__selection" aria-label="Selection">
        <header class="studio-card__header" aria-live="polite">
          <span class="studio-lens-trace__title">
            <span class="studio-lens-trace__badge">S1</span>Selection
          </span>
          <span>{{ current.label }}</span>
        </header>
        <dl>
          <div>
            <dt>Target</dt>
            <dd>{{ current.kind }}</dd>
          </div>
          <div>
            <dt>Computed by</dt>
            <dd>
              <code v-if="current.cells.length">{{ current.cells[0] }}</code>
              <template v-else>No notebook cell</template>
            </dd>
          </div>
          <div v-if="current.cells.length > 1">
            <dt>Upstream</dt>
            <dd class="studio-lens-trace__upstream">
              <template v-for="(cell, index) in current.cells.slice(1)" :key="cell">
                <code>{{ cell }}</code
                ><template v-if="index < current.cells.length - 2">, </template>
              </template>
            </dd>
          </div>
          <div v-if="current.selector">
            <dt>Narrowed to</dt>
            <dd>
              <code>{{ current.selector }}</code>
            </dd>
          </div>
          <div>
            <dt>Placed by</dt>
            <dd>
              <code>{{ current.placement }}</code>
            </dd>
          </div>
        </dl>
        <div class="studio-lens-trace__homes">
          <p><b>Notebook</b>{{ current.notebook }}</p>
          <p><b>View</b>{{ current.view }}</p>
        </div>
      </section>
    </div>

    <figcaption :id="`${id}-caption`">
      <slot>
        Select a part of either view. Lens records what you selected, and Studio adds the cell that
        computed it and the place in the view that shows it.
      </slot>
    </figcaption>
  </figure>
</template>

<style scoped>
.studio-lens-trace__body {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr);
  gap: 1rem;
  align-items: start;
}

@container (max-width: 560px) {
  .studio-lens-trace__body {
    grid-template-columns: minmax(0, 1fr);
  }
}

.studio-lens-trace__mode {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  color: var(--studio-lens);
  font-family: var(--vp-font-family-base);
  font-size: 12px;
  font-weight: 500;
}

.studio-lens-trace__mode i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--studio-lens);
}

.studio-lens-trace__page,
.studio-lens-trace__paper {
  display: grid;
  gap: 14px;
  padding: 26px 18px 18px;
}

.studio-lens-trace__row {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
}

/* Every target shows Lens's dashed outline while Lens selects. The selected
   target turns solid, and the hovered one shows its label chip. */
.studio-lens-trace__target {
  position: relative;
  display: block;
  padding: 8px 10px;
  border: 0;
  border-radius: 6px;
  outline: 1px dashed color-mix(in srgb, var(--studio-lens) 55%, transparent);
  outline-offset: 2px;
  background: var(--vp-c-bg);
  color: var(--vp-c-text-1);
  cursor: crosshair;
  font: inherit;
  text-align: left;
  transition:
    outline-color 0.15s ease,
    background-color 0.15s ease;
}

.studio-lens-trace__target:hover,
.studio-lens-trace__target:focus-visible {
  outline: 1.5px solid var(--studio-lens);
}

.studio-lens-trace__target[aria-pressed="true"] {
  outline: 2px solid var(--studio-lens);
  background: var(--studio-lens-soft);
}

.studio-lens-trace__target:hover::after,
.studio-lens-trace__target:focus-visible::after,
.studio-lens-trace__target[aria-pressed="true"]::after {
  position: absolute;
  bottom: calc(100% + 5px);
  left: -2px;
  z-index: 2;
  padding: 1px 6px;
  border-radius: 3px;
  background: var(--studio-lens);
  color: #fff;
  content: attr(data-chip);
  font-family: var(--vp-font-family-mono);
  font-size: 10.5px;
  font-weight: 500;
  line-height: 16px;
  white-space: nowrap;
  pointer-events: none;
}

.studio-lens-trace__target.is-end::after {
  right: -2px;
  left: auto;
}

/* Large targets keep the chip inside their frame, clear of nearby text. */
:is(.studio-lens-trace__target.is-figure, .studio-lens-trace__target.is-chart)::after {
  top: 6px;
  right: 6px;
  bottom: auto;
  left: auto;
}

.studio-lens-trace__target:hover:not([aria-pressed="true"])::after {
  opacity: 0.85;
}

.studio-lens-trace__target.is-heading {
  font-size: 18px;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.studio-lens-trace__target.is-metric {
  display: grid;
  min-width: 96px;
}

.studio-lens-trace__target small {
  color: var(--vp-c-text-2);
  font-size: 12px;
}

.studio-lens-trace__target.is-metric strong {
  font-size: 22px;
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}

.studio-lens-trace__select {
  display: inline-flex;
  gap: 8px;
  align-items: center;
  font-size: 13px;
}

.studio-lens-trace__select b {
  padding: 2px 22px 2px 8px;
  border: 1px solid var(--studio-chrome-rule);
  border-radius: 6px;
  background: var(--studio-card-bg);
  font-weight: 400;
}

.studio-lens-trace__target.is-chart svg {
  display: block;
  width: 100%;
  height: auto;
  margin-top: 6px;
}

.studio-lens-trace__target.is-chart rect {
  fill: var(--studio-chart);
  opacity: 0.85;
}

.studio-lens-trace__target.is-chart rect[data-marked] {
  opacity: 1;
  stroke: var(--studio-lens);
  stroke-width: 2;
}

.studio-lens-trace__sheet {
  display: grid;
  gap: 12px;
  max-width: 380px;
  margin-inline: auto;
  padding: 26px 26px 22px;
  border-radius: 2px;
  background: #fffefa;
  box-shadow: 0 1px 3px rgb(0 0 0 / 12%);
  color: #1d1d1b;
  font-family: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
}

.studio-lens-trace__sheet .studio-lens-trace__target {
  background: transparent;
  color: inherit;
  font-family: inherit;
}

.studio-lens-trace__paper-title {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
}

.studio-lens-trace__prose {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
}

.studio-lens-trace__target.is-inline {
  display: inline;
  padding: 0 2px;
}

.studio-lens-trace__target.is-figure svg {
  display: block;
  width: 100%;
  height: auto;
}

.studio-lens-trace__target.is-figure rect {
  fill: #4c78a8;
}

.studio-lens-trace__target.is-figure line {
  stroke: #444;
  stroke-width: 1;
}

.studio-lens-trace__target.is-figure small {
  display: block;
  margin-top: 4px;
  color: #555;
  font-size: 11px;
}

.studio-lens-trace__sheet table {
  display: table;
  width: 100%;
  margin: 0;
  border-collapse: collapse;
  font-size: 12px;
}

.studio-lens-trace__sheet :is(th, td) {
  padding: 3px 6px;
  border: 0;
  border-top: 1px solid #d8d6cf;
  background: transparent;
  text-align: left;
}

.studio-lens-trace__sheet tr {
  border: 0;
  background: transparent;
}

.studio-lens-trace__sheet td {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.studio-lens-trace__title {
  display: inline-flex;
  gap: 8px;
  align-items: center;
}

.studio-lens-trace__badge {
  padding: 0 6px;
  border-radius: 4px;
  background: var(--studio-lens);
  color: #fff;
  font-family: var(--vp-font-family-mono);
  font-size: 11px;
  line-height: 18px;
}

.studio-lens-trace__selection dl {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 12px 14px;
}

.studio-lens-trace__selection dl div {
  display: grid;
  gap: 2px;
}

.studio-lens-trace__selection dt {
  color: var(--vp-c-text-2);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.studio-lens-trace__selection dd {
  margin: 0;
  color: var(--vp-c-text-1);
  font-size: 13px;
  line-height: 1.5;
}

.studio-lens-trace__selection code {
  font-size: 12px;
  overflow-wrap: anywhere;
}

.studio-lens-trace__upstream {
  color: var(--vp-c-text-2);
}

.studio-lens-trace__homes {
  display: grid;
  gap: 6px;
  padding: 12px 14px 14px;
  border-top: 1px solid var(--studio-chrome-rule);
  background: var(--vp-c-bg-soft);
}

.studio-lens-trace__homes p {
  display: grid;
  grid-template-columns: 4.75rem 1fr;
  margin: 0;
  color: var(--vp-c-text-2);
  font-size: 13px;
  line-height: 1.5;
}

.studio-lens-trace__homes b {
  color: var(--vp-c-text-1);
  font-weight: 600;
}
</style>
