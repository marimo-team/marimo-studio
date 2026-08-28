export const routes = {
  home: "/",
  guideRoot: "/guide/",
  guide: {
    gettingStarted: "/guide/getting-started",
    views: "/guide/views",
    notebookResults: "/guide/notebook-results",
    workInStudio: "/guide/work-in-studio",
    frontendOptions: "/guide/frontend-options",
    codingAgents: "/guide/coding-agents",
    runAndShare: "/guide/run-and-share",
  },
  example: "/examples/nga",
  referenceRoot: "/reference/",
  reference: {
    cli: "/reference/cli",
    configuration: "/reference/configuration",
    pythonApi: "/reference/python-api",
    providerApi: "/reference/provider-api",
  },
} as const;

export const guideItems = [
  { text: "Create your first page", link: routes.guide.gettingStarted },
  { text: "Create pages for different audiences", link: routes.guide.views },
  { text: "Place notebook results on a page", link: routes.guide.notebookResults },
  { text: "Edit and preview in Studio", link: routes.guide.workInStudio },
  { text: "Use HTML, React, or Svelte", link: routes.guide.frontendOptions },
  { text: "Run or publish a page", link: routes.guide.runAndShare },
];

export const referenceItems = [
  { text: "CLI", link: routes.reference.cli },
  { text: "Python API", link: routes.reference.pythonApi },
  { text: "Configuration", link: routes.reference.configuration },
  { text: "Add another frontend", link: routes.reference.providerApi },
];

export const siteRoutes = [
  routes.home,
  ...guideItems.map(({ link }) => link),
  routes.guide.codingAgents,
  routes.example,
  ...referenceItems.map(({ link }) => link),
];

export const headIcons = {
  light: "/brand/marimo-studio-mark-light.svg",
  dark: "/brand/marimo-studio-mark-dark.svg",
} as const;

export const normalizeBasePath = (value: string | undefined): string => {
  const baseName = value?.trim().replace(/^\/+|\/+$/g, "");
  return baseName ? `/${baseName}` : "";
};

export const withBasePath = (basePath: string, path: string): string => `${basePath}${path}`;
