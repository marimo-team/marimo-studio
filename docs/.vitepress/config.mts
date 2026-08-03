import { defineConfig } from "vitepress";

const repository = "https://github.com/peter-gy/marimo-studio";

function normalizeBasePath(value: string | undefined): string {
  const path = value?.trim() ?? "";
  if (path === "" || path === "/") {
    return "/";
  }
  return `/${path.replace(/^\/+|\/+$/g, "")}/`;
}

const pagesBasePath = process.env.GITHUB_ACTIONS === "true"
  ? process.env.GITHUB_PAGES_BASE_PATH
  : undefined;
const base = normalizeBasePath(pagesBasePath);

export default defineConfig({
  base,
  cleanUrls: true,
  description:
    "Turn Marimo notebooks into focused, Python-backed apps and dashboards.",
  head: [
    ["link", {
      href: `${base}favicon.svg`,
      rel: "icon",
      type: "image/svg+xml",
    }],
  ],
  lang: "en-US",
  lastUpdated: true,
  title: "Marimo Studio",
  themeConfig: {
    editLink: {
      pattern: `${repository}/edit/main/docs/:path`,
      text: "Edit this page on GitHub",
    },
    nav: [
      { text: "Create a view", link: "/getting-started" },
      { text: "Design a view", link: "/build-pages" },
      { text: "Share a view", link: "/deployment" },
      { text: "Reference", link: "/reference" },
      { text: "GitHub", link: repository },
    ],
    outline: [2, 3],
    search: { provider: "local" },
    sidebar: [
      { text: "Build a custom view", link: "/" },
      {
        text: "Build and share",
        items: [
          { text: "Create your first view", link: "/getting-started" },
          { text: "Design a view", link: "/build-pages" },
          { text: "Share a view", link: "/deployment" },
        ],
      },
      {
        text: "Reference",
        items: [
          { text: "Commands and configuration", link: "/reference" },
          { text: "Python API", link: "/python-api" },
        ],
      },
    ],
  },
});
