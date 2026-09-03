export type DocumentationExampleKind = "app" | "report" | "slides";

export interface DocumentationTechnology {
  description: string;
  name: string;
  projectUrl: `https://github.com/${string}`;
}

export const documentationTechnologies = {
  d3: {
    description: "A JavaScript library for data-driven SVG and web visualization.",
    name: "D3",
    projectUrl: "https://github.com/d3/d3",
  },
  echarts: {
    description: "A browser charting library for interactive analytical graphics.",
    name: "ECharts",
    projectUrl: "https://github.com/apache/echarts",
  },
  mapLibre: {
    description: "An open-source TypeScript library for interactive vector maps.",
    name: "MapLibre",
    projectUrl: "https://github.com/maplibre/maplibre-gl-js",
  },
  marimo: {
    description: "Reactive Python notebooks for data, computation, controls, and reusable results.",
    name: "Marimo",
    projectUrl: "https://github.com/marimo-team/marimo",
  },
  mosaic: {
    description: "A framework for linked, scalable visualization over data systems.",
    name: "Mosaic",
    projectUrl: "https://github.com/uwdata/mosaic",
  },
  observablePlot: {
    description: "A concise JavaScript API for exploratory data visualization.",
    name: "Observable Plot",
    projectUrl: "https://github.com/observablehq/plot",
  },
  react: {
    description: "A component library for building interactive web interfaces.",
    name: "React",
    projectUrl: "https://github.com/facebook/react",
  },
  reactPdf: {
    description: "A React renderer for composing PDF documents in the browser or on a server.",
    name: "React PDF",
    projectUrl: "https://github.com/diegomura/react-pdf",
  },
  recharts: {
    description: "A composable charting library built with React.",
    name: "Recharts",
    projectUrl: "https://github.com/recharts/recharts",
  },
  revealJs: {
    description: "An HTML presentation framework for navigable slide decks.",
    name: "Reveal.js",
    projectUrl: "https://github.com/hakimel/reveal.js",
  },
  shower: {
    description: "An HTML presentation engine for keyboard, touch, and overview navigation.",
    name: "Shower",
    projectUrl: "https://github.com/shower/shower",
  },
  svelte: {
    description: "A compiler-based framework for concise reactive web interfaces.",
    name: "Svelte",
    projectUrl: "https://github.com/sveltejs/svelte",
  },
  threeJs: {
    description: "A JavaScript 3D rendering library for the web.",
    name: "Three.js",
    projectUrl: "https://github.com/mrdoob/three.js",
  },
  vanillaHtml: {
    description: "Browser-native HTML, CSS, and JavaScript with no framework runtime.",
    name: "Vanilla HTML",
    projectUrl: "https://github.com/whatwg/html",
  },
} as const satisfies Record<string, DocumentationTechnology>;

export const documentationExampleSource = {
  repository: "https://github.com/marimo-team/marimo-studio",
  revision: "main",
  viewProjectsRoot: "examples/__marimo__/studio",
} as const;

export interface DocumentationExampleView {
  key: string;
  kind: DocumentationExampleKind;
  label: string;
  technologies: readonly DocumentationTechnology[];
}

export interface DocumentationExampleFamily {
  notebook: string;
  slug: string;
  summary: string;
  title: string;
  views: readonly DocumentationExampleView[];
}

export const documentationExampleFamilies = [
  {
    notebook: "examples/athletes.py",
    slug: "athletes",
    summary: "A report, linked explorer, and Three.js briefing share the Rio 2016 roster.",
    title: "Rio 2016 athletes",
    views: [
      {
        key: "overview",
        kind: "report",
        label: "Report",
        technologies: [documentationTechnologies.vanillaHtml],
      },
      {
        key: "explorer",
        kind: "app",
        label: "Explorer",
        technologies: [documentationTechnologies.svelte, documentationTechnologies.mosaic],
      },
      {
        key: "field",
        kind: "slides",
        label: "Field briefing",
        technologies: [
          documentationTechnologies.vanillaHtml,
          documentationTechnologies.shower,
          documentationTechnologies.threeJs,
        ],
      },
    ],
  },
  {
    notebook: "examples/earthquakes.py",
    slug: "earthquakes",
    summary: "A seismic story, operations map, and interactive lesson share one weekly USGS model.",
    title: "Earthquake watch",
    views: [
      {
        key: "story",
        kind: "report",
        label: "Story",
        technologies: [
          documentationTechnologies.vanillaHtml,
          documentationTechnologies.observablePlot,
        ],
      },
      {
        key: "operations",
        kind: "app",
        label: "Operations",
        technologies: [documentationTechnologies.react, documentationTechnologies.mapLibre],
      },
      {
        key: "briefing",
        kind: "slides",
        label: "Interactive lesson",
        technologies: [
          documentationTechnologies.react,
          documentationTechnologies.revealJs,
          documentationTechnologies.d3,
        ],
      },
    ],
  },
  {
    notebook: "examples/occupancy.py",
    slug: "occupancy",
    summary:
      "A reactive scope updates one room-sensor model across a live monitor, model review, and A4 field report.",
    title: "Building occupancy",
    views: [
      {
        key: "monitor",
        kind: "app",
        label: "Monitor",
        technologies: [documentationTechnologies.svelte, documentationTechnologies.echarts],
      },
      {
        key: "model-review",
        kind: "report",
        label: "Model review",
        technologies: [documentationTechnologies.react, documentationTechnologies.recharts],
      },
      {
        key: "pdf-report",
        kind: "report",
        label: "PDF report",
        technologies: [documentationTechnologies.react, documentationTechnologies.reactPdf],
      },
    ],
  },
] as const satisfies readonly DocumentationExampleFamily[];

export const documentationDefaultExamplePaths = documentationExampleFamilies.map(
  ({ slug, views }) => `/examples/${slug}/${views[0].key}/index.html`,
);
