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
  description: "Build custom Python-backed views from Marimo notebook cells.",
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
      { text: "Getting started", link: "/getting-started" },
      { text: "Build a view", link: "/build-pages" },
      { text: "Reference", link: "/reference" },
      { text: "GitHub", link: repository },
    ],
    outline: [2, 3],
    search: { provider: "local" },
    sidebar: [
      { text: "Introduction", link: "/" },
      {
        text: "Guide",
        items: [
          { text: "Getting started", link: "/getting-started" },
          { text: "Build a view", link: "/build-pages" },
          { text: "Deploy", link: "/deployment" },
        ],
      },
      {
        text: "Reference",
        items: [
          { text: "Studio reference", link: "/reference" },
          { text: "Python API", link: "/python-api" },
        ],
      },
    ],
  },
});
