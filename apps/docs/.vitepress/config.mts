import { fileURLToPath } from "node:url";
import { defineConfig } from "vitepress";

const repository = "https://github.com/peter-gy/marimo-studio";
const baseName = process.env.BASE_PATH?.trim().replace(/^\/+|\/+$/g, "");
const basePath = baseName ? `/${baseName}` : "";
const publicDir = fileURLToPath(new URL("../public", import.meta.url));
const publicPath = (path: string): string => `${basePath}${path}`;

export default defineConfig({
  base: basePath ? `${basePath}/` : "/",
  cleanUrls: true,
  description: "Tune your Marimo notebook for every audience.",
  head: [
    [
      "link",
      {
        href: publicPath("/brand/marimo-studio-mark-light.svg"),
        media: "(prefers-color-scheme: light)",
        rel: "icon",
        type: "image/svg+xml",
      },
    ],
    [
      "link",
      {
        href: publicPath("/brand/marimo-studio-mark-dark.svg"),
        media: "(prefers-color-scheme: dark)",
        rel: "icon",
        type: "image/svg+xml",
      },
    ],
  ],
  lang: "en-US",
  lastUpdated: true,
  srcDir: "../../docs",
  title: "Marimo Studio",
  themeConfig: {
    editLink: {
      pattern: `${repository}/edit/main/docs/:path`,
      text: "Edit this page on GitHub",
    },
    logo: {
      alt: "Marimo Studio",
      dark: "/brand/marimo-studio-lockup-horizontal-dark.svg",
      light: "/brand/marimo-studio-lockup-horizontal-light.svg",
    },
    nav: [
      { text: "How it works", link: "/how-it-works" },
      {
        text: "Guide",
        items: [
          { text: "Getting started", link: "/getting-started" },
          { text: "Create and manage views", link: "/views" },
          { text: "Design a view", link: "/design-views" },
          { text: "Share a view", link: "/share-views" },
        ],
      },
      { text: "Reference", link: "/reference" },
    ],
    outline: [2, 3],
    search: { provider: "local" },
    sidebar: [
      {
        text: "Introduction",
        collapsed: false,
        items: [
          { text: "Overview", link: "/" },
          { text: "How it works", link: "/how-it-works" },
          { text: "Getting started", link: "/getting-started" },
        ],
      },
      {
        text: "Guide",
        collapsed: false,
        items: [
          { text: "Create and manage views", link: "/views" },
          { text: "Design a view", link: "/design-views" },
          { text: "Share a view", link: "/share-views" },
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
    siteTitle: false,
    socialLinks: [{ icon: "github", link: repository }],
  },
  vite: { publicDir },
});
