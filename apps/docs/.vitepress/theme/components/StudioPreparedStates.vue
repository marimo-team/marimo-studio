<script setup lang="ts">
import { computed, ref, useId, watch } from "vue";

import StudioCode from "./StudioCode.vue";
import { useWideFigure } from "./wide-figure.ts";

type Runtime = "prepared" | "python";

const steps = ["2.5", "3.0", "3.5", "4.0"] as const;
type Magnitude = (typeof steps)[number];

// Events per day this week for each minimum magnitude the slider can send.
const results = {
  "2.5": [31, 24, 29, 22, 27, 25, 26],
  "3.0": [16, 12, 15, 11, 14, 15, 14],
  "3.5": [7, 5, 6, 4, 7, 6, 6],
  "4.0": [3, 2, 3, 2, 3, 2, 3],
} satisfies Record<Magnitude, readonly number[]>;
const prepared: ReadonlySet<Magnitude> = new Set(["2.5", "3.0", "4.0"]);
const days = ["M", "T", "W", "T", "F", "S", "S"];

const states = [
  "schema: marimo-export.states.v1",
  "default_state: matrix-000000",
  "matrix:",
  "  minimum_magnitude: [2.5, 3.0, 4.0]",
].join("\n");

const runtime = ref<Runtime>("prepared");
const position = ref(0);
const requested = computed<Magnitude>(() => steps[position.value] ?? "2.5");
const shown = ref<Magnitude>("2.5");

// A prepared export moves only between saved states. The Python runtime
// computes every value the slider sends.
watch(
  [requested, runtime],
  ([value, mode]) => {
    if (mode === "python" || prepared.has(value)) {
      shown.value = value;
    }
  },
  { immediate: true },
);

const counts = computed(() => results[shown.value]);
const total = computed(() => counts.value.reduce((sum, count) => sum + count, 0));
const skipped = computed(() => runtime.value === "prepared" && !prepared.has(requested.value));
const id = useId();
const figure = ref<HTMLElement>();
const wide = useWideFigure(figure);

const tickState = (value: Magnitude): string => {
  if (runtime.value === "python") {
    return "computed live";
  }
  return prepared.has(value) ? "prepared" : "not prepared";
};

const runtimes: readonly { key: Runtime; label: string }[] = [
  { key: "prepared", label: "Prepared export" },
  { key: "python", label: "Python runtime" },
];
</script>

<template>
  <figure
    ref="figure"
    class="studio-figure-block studio-prepared"
    :style="wide"
    :aria-labelledby="`${id}-caption`"
  >
    <div class="studio-choice" role="group" aria-label="Runtime">
      <button
        v-for="item in runtimes"
        :key="item.key"
        type="button"
        :aria-pressed="runtime === item.key"
        @click="runtime = item.key"
      >
        {{ item.label }}
      </button>
    </div>

    <div class="studio-prepared__body">
      <section
        class="studio-card studio-prepared__file"
        :data-muted="runtime === 'python' || undefined"
        aria-label="states.yaml"
      >
        <header class="studio-card__header">
          <span>Prepared states</span><span>states.yaml</span>
        </header>
        <StudioCode :code="states" language="yaml" :active="runtime === 'prepared' ? [3] : []" />
        <p v-if="runtime === 'prepared'">
          Export runs the notebook once for each listed value and saves every result.
        </p>
        <p v-else>The Python runtime ignores this file and runs the notebook for each change.</p>
      </section>

      <section class="studio-card" aria-label="View page">
        <header class="studio-card__header"><span>HTML page</span><span>index.html</span></header>
        <div class="studio-prepared__page">
          <label class="studio-prepared__slider">
            <span>
              Minimum magnitude <b>{{ requested }}</b>
            </span>
            <input v-model.number="position" type="range" min="0" max="3" step="1" />
          </label>
          <ol class="studio-prepared__ticks" aria-label="Slider values">
            <li
              v-for="value in steps"
              :key="value"
              :data-prepared="(runtime === 'prepared' && prepared.has(value)) || undefined"
              :data-live="runtime === 'python' || undefined"
              :data-shown="value === shown || undefined"
            >
              <i aria-hidden="true" />{{ value }}
              <span class="studio-prepared__sr">
                {{ tickState(value) }}
              </span>
            </li>
          </ol>

          <div class="studio-prepared__result">
            <p>
              Events this week <strong>{{ total }}</strong>
              <span>at magnitude {{ shown }} and above</span>
            </p>
            <svg
              viewBox="0 0 224 64"
              role="img"
              :aria-label="`Events per day: ${counts.join(', ')}`"
            >
              <g v-for="(count, day) in counts" :key="day">
                <rect
                  :x="4 + day * 32"
                  :y="52 - count * 1.5"
                  width="22"
                  :height="count * 1.5"
                  rx="2"
                />
                <text :x="15 + day * 32" y="63" text-anchor="middle">{{ days[day] }}</text>
              </g>
            </svg>
          </div>

          <p
            class="studio-prepared__status"
            :data-warning="skipped || undefined"
            aria-live="polite"
          >
            <template v-if="skipped">
              Export prepared no state for {{ requested }}, so the page keeps the
              {{ shown }} results. Preflight warns about this gap with
              <code>prepared-states-skip-control-values</code>.
            </template>
            <template v-else-if="runtime === 'prepared'">
              The page loads the saved {{ shown }} state. No Python runs.
            </template>
            <template v-else>
              The session reruns the cells that read the slider and sends the new results.
            </template>
          </p>
        </div>
      </section>
    </div>

    <figcaption :id="`${id}-caption`">
      <slot>
        Move the slider to 3.5, a value the export did not prepare, then compare the Python runtime.
      </slot>
    </figcaption>
  </figure>
</template>

<style scoped>
.studio-prepared__body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr);
  gap: 1rem;
  align-items: start;
}

@container (max-width: 540px) {
  .studio-prepared__body {
    grid-template-columns: minmax(0, 1fr);
  }
}

.studio-prepared__file {
  transition: opacity 0.25s ease;
}

.studio-prepared__file[data-muted] {
  opacity: 0.55;
}

.studio-prepared__file p {
  margin: 0;
  padding: 10px 12px 12px;
  border-top: 1px solid var(--studio-chrome-rule);
  color: var(--vp-c-text-2);
  font-size: 13px;
  line-height: 1.5;
}

.studio-prepared__page {
  display: grid;
  gap: 12px;
  padding: 14px 16px 16px;
}

.studio-prepared__slider {
  display: grid;
  gap: 6px;
  color: var(--vp-c-text-1);
  font-size: 13px;
}

.studio-prepared__slider b {
  font-variant-numeric: tabular-nums;
}

.studio-prepared__slider input {
  width: 100%;
  accent-color: var(--studio-link);
}

.studio-prepared__ticks {
  display: flex;
  justify-content: space-between;
  margin: -4px 0 0;
  padding: 0;
  list-style: none;
}

.studio-prepared__ticks li {
  display: inline-flex;
  gap: 5px;
  align-items: center;
  margin: 0;
  color: var(--vp-c-text-3);
  font-family: var(--vp-font-family-mono);
  font-size: 11px;
}

.studio-prepared__ticks i {
  width: 8px;
  height: 8px;
  border: 1.25px dashed var(--vp-c-text-3);
  border-radius: 50%;
}

.studio-prepared__ticks li:is([data-prepared], [data-live]) {
  color: var(--vp-c-text-2);
}

.studio-prepared__ticks li:is([data-prepared], [data-live]) i {
  border: 0;
  background: var(--studio-link);
}

.studio-prepared__ticks li[data-shown] {
  color: var(--vp-c-text-1);
  font-weight: 600;
}

.studio-prepared__sr {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}

.studio-prepared__result {
  padding-top: 4px;
}

.studio-prepared__result p {
  display: flex;
  flex-wrap: wrap;
  gap: 0 8px;
  align-items: baseline;
  margin: 0 0 6px;
  color: var(--vp-c-text-1);
  font-size: 13px;
}

.studio-prepared__result strong {
  font-size: 20px;
  font-variant-numeric: tabular-nums;
}

.studio-prepared__result span {
  color: var(--vp-c-text-2);
  font-size: 12px;
}

.studio-prepared__result svg {
  display: block;
  width: 100%;
  max-width: 280px;
  height: auto;
}

.studio-prepared__result rect {
  fill: var(--studio-chart);
}

.studio-prepared__result text {
  fill: var(--vp-c-text-2);
  font-size: 9px;
}

.studio-prepared__status {
  margin: 0;
  padding: 8px 10px;
  border-left: 2px solid var(--studio-link);
  border-radius: 0 6px 6px 0;
  background: var(--studio-link-soft);
  color: var(--vp-c-text-1);
  font-size: 13px;
  line-height: 1.5;
}

.studio-prepared__status[data-warning] {
  border-left-color: var(--vp-c-warning-1);
  background: var(--vp-c-warning-soft);
}

.studio-prepared__status code {
  font-size: 11.5px;
  overflow-wrap: anywhere;
}
</style>
