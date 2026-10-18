<script setup lang="ts">
import { computed, ref, useId } from "vue";

import { useWideFigure } from "./wide-figure.ts";

type Mode = "build" | "rerun" | "render";
type NodeId = "project" | "provider" | "page" | "session";
type EdgeId = "build" | "page" | "results" | "render";

interface Node {
  id: NodeId;
  x: number;
  y: number;
  width: number;
  height: number;
}

interface Edge {
  id: EdgeId;
  path: string;
  label: { x: number; y: number; anchor?: "start" | "middle" | "end"; rotate?: boolean };
  both?: boolean;
}

interface Layout {
  name: "wide" | "narrow";
  width: number;
  height: number;
  nodes: readonly Node[];
  edges: readonly Edge[];
}

const text: Record<NodeId, { title: string; detail: string }> = {
  project: { title: "View project", detail: "Your source files" },
  provider: { title: "View provider", detail: "build() and render()" },
  page: { title: "Page", detail: "HTML in the browser" },
  session: { title: "Session", detail: "marimo runs analysis.py" },
};

const edgeText: Record<EdgeId, string> = {
  build: "build",
  page: "files",
  results: "results by name",
  render: "values as JSON",
};

// Two fixed drawings on an 8 px grid. CSS shows the narrow one in narrow
// containers, so the labels keep their size instead of scaling down.
const layouts: readonly Layout[] = [
  {
    name: "wide",
    width: 640,
    height: 240,
    nodes: [
      { id: "project", x: 4, y: 24, width: 176, height: 64 },
      { id: "provider", x: 232, y: 24, width: 176, height: 64 },
      { id: "page", x: 460, y: 24, width: 176, height: 64 },
      { id: "session", x: 304, y: 168, width: 272, height: 64 },
    ],
    edges: [
      { id: "build", path: "M 180 56 H 226", label: { x: 203, y: 46 } },
      { id: "page", path: "M 408 56 H 454", label: { x: 431, y: 46 } },
      { id: "render", path: "M 344 168 V 94", label: { x: 336, y: 134, anchor: "end" } },
      {
        id: "results",
        path: "M 540 162 V 94",
        label: { x: 532, y: 134, anchor: "end" },
        both: true,
      },
    ],
  },
  {
    name: "narrow",
    width: 344,
    height: 512,
    nodes: [
      { id: "project", x: 8, y: 8, width: 264, height: 64 },
      { id: "provider", x: 8, y: 136, width: 264, height: 64 },
      { id: "page", x: 8, y: 264, width: 264, height: 64 },
      { id: "session", x: 8, y: 432, width: 264, height: 64 },
    ],
    edges: [
      { id: "build", path: "M 140 72 V 130", label: { x: 150, y: 106, anchor: "start" } },
      { id: "page", path: "M 140 200 V 258", label: { x: 150, y: 234, anchor: "start" } },
      {
        id: "results",
        path: "M 140 426 V 334",
        label: { x: 150, y: 384, anchor: "start" },
        both: true,
      },
      {
        id: "render",
        path: "M 272 464 H 312 V 168 H 278",
        label: { x: 330, y: 316, rotate: true },
      },
    ],
  },
];

const modes: Record<
  Mode,
  { label: string; nodes: readonly NodeId[]; edges: readonly EdgeId[]; steps: readonly string[] }
> = {
  build: {
    label: "Save view source",
    nodes: ["project", "provider", "page"],
    edges: ["build", "page"],
    steps: [
      "You save `index.html` in Source, in your own editor, or through a coding agent.",
      "Studio copies the build inputs into a snapshot and calls the provider's `build()`.",
      "The provider writes the page: an HTML entry file and the files it loads, with empty hosts.",
      "Preview shows the new page. The session is still running, so its results fill the hosts at once.",
    ],
  },
  rerun: {
    label: "Change a control",
    nodes: ["page", "session"],
    edges: ["results"],
    steps: [
      "A reader picks **South** in the dropdown that `<marimo-cell>` shows.",
      "The browser sends the control's new value to the session.",
      "marimo reruns `summary` and every other cell that reads the control.",
      "Studio sends the new `summary.orders` to its host as JSON. No build runs.",
    ],
  },
  render: {
    label: "Compile a PDF",
    nodes: ["session", "provider", "page"],
    edges: ["render", "page"],
    steps: [
      "The session recomputes `summary.orders`, which a Typst view's `main.typ` reads.",
      "Studio calls the provider's `render()` with values as JSON and figures as media, such as images.",
      "The provider compiles a new `main.pdf` with its own tool.",
      "The page's render host shows the new PDF with a download link.",
    ],
  },
};
const order: readonly Mode[] = ["build", "rerun", "render"];

const mode = ref<Mode>("build");
const active = computed(() => modes[mode.value]);
const id = useId();
const figure = ref<HTMLElement>();
const wide = useWideFigure(figure);

// Inline code and bold in step text, without a Markdown renderer.
const parts = (step: string): { text: string; kind: "plain" | "code" | "strong" }[] =>
  step
    .split(/(`[^`]+`|\*\*[^*]+\*\*)/)
    .filter(Boolean)
    .map((part) => {
      if (part.startsWith("`")) {
        return { text: part.slice(1, -1), kind: "code" };
      }
      if (part.startsWith("**")) {
        return { text: part.slice(2, -2), kind: "strong" };
      }
      return { text: part, kind: "plain" };
    });

const litNode = (node: NodeId): boolean => active.value.nodes.includes(node);
const litEdge = (edge: EdgeId): boolean => active.value.edges.includes(edge);
</script>

<template>
  <figure
    ref="figure"
    class="studio-figure-block studio-pipeline"
    :style="wide"
    :aria-labelledby="`${id}-caption`"
  >
    <div class="studio-choice" role="group" aria-label="What happens when">
      <button
        v-for="item in order"
        :key="item"
        type="button"
        :aria-pressed="mode === item"
        @click="mode = item"
      >
        {{ modes[item].label }}
      </button>
    </div>

    <svg
      v-for="layout in layouts"
      :key="layout.name"
      :class="`studio-pipeline__drawing is-${layout.name}`"
      :viewBox="`0 0 ${layout.width} ${layout.height}`"
      :width="layout.width"
      :height="layout.height"
      aria-hidden="true"
    >
      <defs>
        <marker
          v-for="state in ['idle', 'lit']"
          :id="`${id}-${layout.name}-${state}`"
          :key="state"
          viewBox="0 0 8 8"
          refX="7"
          refY="4"
          markerWidth="7"
          markerHeight="7"
          orient="auto-start-reverse"
        >
          <path d="M 1 1 L 7 4 L 1 7" :class="`studio-pipeline__arrow is-${state}`" />
        </marker>
      </defs>

      <g
        v-for="edge in layout.edges"
        :key="edge.id"
        class="studio-pipeline__edge"
        :data-lit="litEdge(edge.id) || undefined"
      >
        <path
          :d="edge.path"
          :marker-end="`url(#${id}-${layout.name}-${litEdge(edge.id) ? 'lit' : 'idle'})`"
          :marker-start="
            edge.both
              ? `url(#${id}-${layout.name}-${litEdge(edge.id) ? 'lit' : 'idle'})`
              : undefined
          "
        />
        <text
          :x="edge.label.x"
          :y="edge.label.y"
          :text-anchor="edge.label.anchor ?? 'middle'"
          :transform="edge.label.rotate ? `rotate(-90 ${edge.label.x} ${edge.label.y})` : undefined"
        >
          {{ edgeText[edge.id] }}
        </text>
      </g>

      <g
        v-for="node in layout.nodes"
        :key="node.id"
        class="studio-pipeline__node"
        :data-node="node.id"
        :data-lit="litNode(node.id) || undefined"
      >
        <rect :x="node.x" :y="node.y" :width="node.width" :height="node.height" rx="12" />
        <text :x="node.x + 16" :y="node.y + node.height / 2 - 4" class="studio-pipeline__title">
          {{ text[node.id].title }}
        </text>
        <text :x="node.x + 16" :y="node.y + node.height / 2 + 15" class="studio-pipeline__detail">
          {{ text[node.id].detail }}
        </text>
      </g>
    </svg>

    <ol class="studio-note studio-pipeline__steps">
      <li v-for="(step, index) in active.steps" :key="`${mode}-${index}`">
        <template v-for="(part, position) in parts(step)" :key="position">
          <code v-if="part.kind === 'code'">{{ part.text }}</code>
          <strong v-else-if="part.kind === 'strong'">{{ part.text }}</strong>
          <template v-else>{{ part.text }}</template>
        </template>
      </li>
    </ol>

    <figcaption :id="`${id}-caption`">
      <slot>
        The view project and the notebook meet in the page. Choose an event to see which parts take
        part and what passes between them.
      </slot>
    </figcaption>
  </figure>
</template>

<style scoped>
.studio-pipeline__drawing {
  display: block;
  width: 100%;
  max-width: 100%;
  height: auto;
  margin-inline: auto;
  overflow: visible;
}

.studio-pipeline__drawing.is-wide {
  max-width: 640px;
}

.studio-pipeline__drawing.is-narrow {
  display: none;
  max-width: 344px;
}

@container (max-width: 560px) {
  .studio-pipeline__drawing.is-wide {
    display: none;
  }

  .studio-pipeline__drawing.is-narrow {
    display: block;
  }
}

.studio-pipeline__node rect {
  fill: var(--studio-card-bg);
  stroke: var(--studio-card-border);
  stroke-width: 1;
  transition: stroke 0.25s ease;
}

/* The session runs the notebook, so it carries the notebook's chrome color. */
.studio-pipeline__node[data-node="session"] rect {
  fill: var(--studio-notebook-chrome);
}

.studio-pipeline__node[data-node="session"] .studio-pipeline__title {
  fill: var(--studio-notebook-label);
}

.studio-pipeline__node[data-lit] rect {
  stroke: var(--studio-link);
  stroke-width: 1.5;
}

.studio-pipeline__node:not([data-lit]),
.studio-pipeline__edge:not([data-lit]) {
  opacity: 0.45;
}

.studio-pipeline__node,
.studio-pipeline__edge {
  transition: opacity 0.25s ease;
}

.studio-pipeline__title {
  fill: var(--studio-chrome-label);
  font-size: 13.5px;
  font-weight: 600;
}

.studio-pipeline__detail {
  fill: var(--vp-c-text-2);
  font-size: 12px;
}

.studio-pipeline__edge path {
  fill: none;
  stroke: var(--vp-c-text-3);
  stroke-width: 1.25;
}

.studio-pipeline__edge[data-lit] path {
  stroke: var(--studio-link);
  stroke-width: 1.75;
}

.studio-pipeline__edge text {
  fill: var(--vp-c-text-2);
  font-family: var(--vp-font-family-mono);
  font-size: 11px;
}

.studio-pipeline__edge[data-lit] text {
  fill: var(--studio-link);
}

.studio-pipeline__arrow {
  fill: none;
  stroke-width: 1.3;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.studio-pipeline__arrow.is-idle {
  stroke: var(--vp-c-text-3);
}

.studio-pipeline__arrow.is-lit {
  stroke: var(--studio-link);
}

.studio-pipeline__steps {
  margin: 1.25rem 0 0;
  padding-left: 34px;
}

.studio-pipeline__steps li + li {
  margin-top: 4px;
}

.studio-pipeline__steps code {
  font-size: 12px;
}
</style>
