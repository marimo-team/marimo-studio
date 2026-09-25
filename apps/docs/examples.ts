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
  notebookKit: {
    description: "Reactive JavaScript, Markdown, and HTML cells in an open notebook format.",
    name: "Notebook Kit",
    projectUrl: "https://github.com/observablehq/notebook-kit",
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
  label: string;
  technologies: readonly DocumentationTechnology[];
}

export interface DocumentationExampleFamily {
  notebook: string;
  slug: string;
  title: string;
  views: readonly DocumentationExampleView[];
}

export const documentationExampleFamilies = [
  {
    notebook: "examples/quadratic_program.py",
    slug: "quadratic-programs",
    title: "Quadratic programs",
    views: [
      {
        key: "lecture",
        label: "Lecture",
        technologies: [documentationTechnologies.react, documentationTechnologies.revealJs],
      },
      {
        key: "explainer",
        label: "Explainer",
        technologies: [documentationTechnologies.vanillaHtml],
      },
      {
        key: "lab",
        label: "Lab",
        technologies: [documentationTechnologies.svelte, documentationTechnologies.d3],
      },
    ],
  },
  {
    notebook: "examples/athletes.py",
    slug: "athletes",
    title: "Rio 2016 athletes",
    views: [
      {
        key: "overview",
        label: "Report",
        technologies: [documentationTechnologies.vanillaHtml],
      },
      {
        key: "explorer",
        label: "Dashboard",
        technologies: [documentationTechnologies.svelte, documentationTechnologies.mosaic],
      },
      {
        key: "field",
        label: "Slides",
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
    title: "Earthquake watch",
    views: [
      {
        key: "story",
        label: "Story",
        technologies: [
          documentationTechnologies.vanillaHtml,
          documentationTechnologies.observablePlot,
        ],
      },
      {
        key: "operations",
        label: "Map",
        technologies: [documentationTechnologies.react, documentationTechnologies.mapLibre],
      },
      {
        key: "briefing",
        label: "Slides",
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
    title: "Building occupancy",
    views: [
      {
        key: "monitor",
        label: "Dashboard",
        technologies: [
          documentationTechnologies.notebookKit,
          documentationTechnologies.observablePlot,
        ],
      },
      {
        key: "model-review",
        label: "Report",
        technologies: [documentationTechnologies.react, documentationTechnologies.recharts],
      },
      {
        key: "pdf-report",
        label: "PDF",
        technologies: [documentationTechnologies.react, documentationTechnologies.reactPdf],
      },
    ],
  },
] as const satisfies readonly DocumentationExampleFamily[];

export const documentationDefaultExamplePaths = documentationExampleFamilies.map(
  ({ slug, views }) => `/examples/${slug}/${views[0].key}/index.html`,
);
