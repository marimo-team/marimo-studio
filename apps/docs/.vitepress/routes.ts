export const routes = {
  home: "/",
  whatIsStudio: "/what-is-studio",
  whyStudio: "/why-studio",
  examplesRoot: "/examples/",
  examples: {
    index: "/examples/",
    athletes: "/examples/athletes",
    earthquakes: "/examples/earthquakes",
    occupancy: "/examples/occupancy",
  },
  guideRoot: "/guide/",
  guide: {
    index: "/guide/",
    gettingStarted: "/guide/getting-started",
    views: "/guide/views",
    notebookResults: "/guide/notebook-results",
    workInStudio: "/guide/work-in-studio",
    manageSource: "/guide/manage-source",
    styling: "/guide/styling",
    frontendOptions: "/guide/frontend-options",
    codingAgents: "/guide/coding-agents",
    navigationAndSessions: "/guide/navigation-and-sessions",
    runAndShare: "/guide/run-and-share",
    deploy: "/guide/deploy",
    troubleshooting: "/guide/troubleshooting",
  },
  referenceRoot: "/reference/",
  reference: {
    index: "/reference/",
    cli: "/reference/cli",
    compatibility: "/reference/compatibility",
    configuration: "/reference/configuration",
    pythonApi: "/reference/python-api",
    providerApi: "/reference/provider-api",
    builtInProviders: "/reference/built-in-providers",
    projections: "/reference/projections",
    identities: "/reference/identities",
    limits: "/reference/limits",
    errorsAndJson: "/reference/errors-and-json",
  },
} as const;

export const exampleItems = [
  { text: "Examples", link: routes.examples.index },
  { text: "Rio 2016 athletes", link: routes.examples.athletes },
  { text: "Earthquake watch", link: routes.examples.earthquakes },
  { text: "Building occupancy", link: routes.examples.occupancy },
];

export const introductionItems = [
  { text: "What is Studio?", link: routes.whatIsStudio },
  { text: "Why Studio?", link: routes.whyStudio },
];

export const startItems = [
  { text: "Start here", link: routes.guide.index },
  { text: "Create your first view", link: routes.guide.gettingStarted },
  { text: "One notebook, many views", link: routes.guide.views },
  { text: "Place notebook results in a view", link: routes.guide.notebookResults },
];

export const authoringItems = [
  { text: "Edit and preview in Studio", link: routes.guide.workInStudio },
  { text: "Manage view source", link: routes.guide.manageSource },
  { text: "Style a view", link: routes.guide.styling },
  { text: "Choose a frontend", link: routes.guide.frontendOptions },
  { text: "Author with a coding agent", link: routes.guide.codingAgents },
];

export const deliveryItems = [
  { text: "Navigate and preserve state", link: routes.guide.navigationAndSessions },
  { text: "Run or export a view", link: routes.guide.runAndShare },
  { text: "Deploy a live Python view", link: routes.guide.deploy },
  { text: "Troubleshoot Studio", link: routes.guide.troubleshooting },
];

export const guideItems = [...startItems, ...authoringItems, ...deliveryItems];

export const referenceItems = [
  { text: "Overview", link: routes.reference.index },
  { text: "CLI", link: routes.reference.cli },
  { text: "Python API", link: routes.reference.pythonApi },
  { text: "Configuration", link: routes.reference.configuration },
  { text: "Projection DOM API", link: routes.reference.projections },
  { text: "Built-in providers", link: routes.reference.builtInProviders },
  { text: "Compatibility and support", link: routes.reference.compatibility },
  { text: "View provider API", link: routes.reference.providerApi },
  { text: "Identities and state", link: routes.reference.identities },
  { text: "Limits", link: routes.reference.limits },
  { text: "Errors and JSON", link: routes.reference.errorsAndJson },
];

export const projectItems = [
  {
    text: "Issues and support",
    link: "https://github.com/marimo-team/marimo-studio/issues",
  },
  {
    text: "Security policy",
    link: "https://github.com/marimo-team/marimo-studio/blob/main/SECURITY.md",
  },
  {
    text: "Contributing",
    link: "https://github.com/marimo-team/marimo-studio/blob/main/CONTRIBUTING.md",
  },
];

export const siteRoutes = [
  routes.home,
  ...introductionItems.map(({ link }) => link),
  ...exampleItems.map(({ link }) => link),
  ...guideItems.map(({ link }) => link),
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
