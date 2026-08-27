export const routes = {
  home: "/",
  overview: "/overview",
  guide: {
    index: "/guide/",
    gettingStarted: "/guide/getting-started",
    views: "/guide/views",
    notebookResults: "/guide/notebook-results",
    liveAuthoring: "/guide/live-authoring",
    authoringOptions: "/guide/authoring-options",
    codingAgents: "/guide/coding-agents",
    runAndShare: "/guide/run-and-share",
  },
  examples: {
    index: "/examples/",
    nga: "/examples/nga",
  },
  reference: {
    index: "/reference/",
    viewProject: "/reference/view-project",
    providerApi: "/reference/provider-api",
    projections: "/reference/projections",
    agentApi: "/reference/agent-api",
    cli: "/reference/cli",
    configuration: "/reference/configuration",
    runtimes: "/reference/runtimes",
    pythonApi: "/reference/python-api",
  },
} as const;

export const guideItems = [
  { text: "Guide overview", link: routes.guide.index },
  { text: "Create your first view", link: routes.guide.gettingStarted },
  { text: "Create and manage views", link: routes.guide.views },
  { text: "Use notebook results", link: routes.guide.notebookResults },
  { text: "Author with the live workspace", link: routes.guide.liveAuthoring },
  { text: "Choose an authoring option", link: routes.guide.authoringOptions },
  { text: "Agent-native authoring", link: routes.guide.codingAgents },
  { text: "Run, export, and share", link: routes.guide.runAndShare },
];

export const exampleItems = [
  { text: "Examples overview", link: routes.examples.index },
  { text: "NGA collection explorer", link: routes.examples.nga },
];

export const referenceItems = [
  { text: "Reference overview", link: routes.reference.index },
  { text: "View projects", link: routes.reference.viewProject },
  { text: "Provider API", link: routes.reference.providerApi },
  { text: "Projections", link: routes.reference.projections },
  { text: "Agent API", link: routes.reference.agentApi },
  { text: "CLI", link: routes.reference.cli },
  { text: "Notebook configuration", link: routes.reference.configuration },
  { text: "Runtime behavior", link: routes.reference.runtimes },
  { text: "Python API", link: routes.reference.pythonApi },
];

export const siteRoutes = [
  routes.home,
  routes.overview,
  ...guideItems.map(({ link }) => link),
  ...exampleItems.map(({ link }) => link),
  ...referenceItems.map(({ link }) => link),
];

export const redirects = {
  "examples/collection-research": routes.examples.nga,
  "examples/revenue-forecast": routes.examples.index,
  "guide/web-platform": routes.guide.authoringOptions,
  "reference/view-document": routes.reference.viewProject,
} as const;

export const headIcons = {
  light: "/brand/marimo-studio-mark-light.svg",
  dark: "/brand/marimo-studio-mark-dark.svg",
} as const;

export const normalizeBasePath = (value: string | undefined): string => {
  const baseName = value?.trim().replace(/^\/+|\/+$/g, "");
  return baseName ? `/${baseName}` : "";
};

export const withBasePath = (basePath: string, path: string): string => `${basePath}${path}`;
