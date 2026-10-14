export const routes = {
  home: "/",
  whatIsStudio: "/what-is-studio",
  examplesRoot: "/examples/",
  examples: {
    index: "/examples/",
    quadraticPrograms: "/examples/quadratic-programs",
    athletes: "/examples/athletes",
    earthquakes: "/examples/earthquakes",
    occupancy: "/examples/occupancy",
  },
  guideRoot: "/guide/",
  guide: {
    index: "/guide/",
    gettingStarted: "/guide/getting-started",
    codingAgents: "/guide/coding-agents",
    notebookResults: "/guide/notebook-results",
    formats: "/guide/formats",
    workInStudio: "/guide/work-in-studio",
    styling: "/guide/styling",
    viewProviders: "/guide/view-providers",
    runAndShare: "/guide/run-and-share",
    navigationAndSessions: "/guide/navigation-and-sessions",
    deploy: "/guide/deploy",
    marimohub: "/guide/marimohub",
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
  { text: "Quadratic programs", link: routes.examples.quadraticPrograms },
  { text: "Rio 2016 athletes", link: routes.examples.athletes },
  { text: "Earthquake watch", link: routes.examples.earthquakes },
  { text: "Building occupancy", link: routes.examples.occupancy },
];

export const introductionItems = [{ text: "What is Studio?", link: routes.whatIsStudio }];

export const startItems = [
  { text: "Guide overview", link: routes.guide.index },
  { text: "Getting started", link: routes.guide.gettingStarted },
  { text: "Author with a coding agent", link: routes.guide.codingAgents },
];

export const authoringItems = [
  { text: "Place notebook results", link: routes.guide.notebookResults },
  { text: "Choose a format", link: routes.guide.formats },
  { text: "Work in Studio", link: routes.guide.workInStudio },
  { text: "Style a page", link: routes.guide.styling },
  { text: "Add a view provider", link: routes.guide.viewProviders },
];

export const deliveryItems = [
  { text: "Run or export a view", link: routes.guide.runAndShare },
  { text: "Link views and keep state", link: routes.guide.navigationAndSessions },
  { text: "Deploy a live Python view", link: routes.guide.deploy },
  { text: "Use Studio in marimohub", link: routes.guide.marimohub },
  { text: "Troubleshoot Studio", link: routes.guide.troubleshooting },
];

export const guideItems = [...startItems, ...authoringItems, ...deliveryItems];

export const referenceItems = [
  { text: "Overview", link: routes.reference.index },
  { text: "CLI", link: routes.reference.cli },
  { text: "Python API", link: routes.reference.pythonApi },
  { text: "Configuration", link: routes.reference.configuration },
  { text: "Notebook result projections", link: routes.reference.projections },
  { text: "Built-in view providers", link: routes.reference.builtInProviders },
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
