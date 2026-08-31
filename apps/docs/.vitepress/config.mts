import { fileURLToPath } from "node:url";
import { defineConfig, type HeadConfig, type Plugin, type UserConfig } from "vitepress";
import llmstxt from "vitepress-plugin-llms";

import {
  guideItems,
  headIcons,
  normalizeBasePath,
  referenceItems,
  routes,
  withBasePath,
} from "./routes.ts";

const repository = "https://github.com/marimo-team/marimo-studio";
const siteUrl = new URL("https://marimo-team.github.io/marimo-studio/");
const socialDescription =
  "Turn one reactive Marimo notebook into focused web pages for different audiences.";
const basePath = normalizeBasePath(process.env.BASE_PATH);
const publicDir = fileURLToPath(new URL("../public", import.meta.url));
const publicPath = (path: string): string => withBasePath(basePath, path);
const canonicalUrl = (page: string): string => {
  const route = page
    .replace(/^\/+/, "")
    .replace(/(^|\/)index\.md$/, "$1")
    .replace(/\.md$/, "");
  return new URL(route, siteUrl).href;
};
// SAFETY: vitepress-plugin-llms returns two Vite plugins whose standard hooks
// are loaded and executed by this VitePress version during every docs build.
const llmsPlugins = llmstxt({
  domain: siteUrl.href.replace(/\/$/, ""),
  excludeIndexPage: false,
}) as [Plugin, Plugin];
const viteConfig: UserConfig["vite"] = {
  plugins: llmsPlugins,
  publicDir,
};
export default defineConfig({
  base: basePath ? `${basePath}/` : "/",
  cleanUrls: true,
  description: socialDescription,
  head: [
    [
      "link",
      {
        href: publicPath(headIcons.light),
        media: "(prefers-color-scheme: light)",
        rel: "icon",
        type: "image/svg+xml",
      },
    ],
    [
      "link",
      {
        href: publicPath(headIcons.dark),
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
  transformHead({ description, page, title }): HeadConfig[] {
    const canonical = canonicalUrl(page);
    const pageDescription = description || socialDescription;

    return [
      ["link", { href: canonical, rel: "canonical" }],
      ["meta", { content: "website", property: "og:type" }],
      ["meta", { content: "Marimo Studio", property: "og:site_name" }],
      ["meta", { content: "en_US", property: "og:locale" }],
      ["meta", { content: title, property: "og:title" }],
      ["meta", { content: pageDescription, property: "og:description" }],
      ["meta", { content: canonical, property: "og:url" }],
      ["meta", { content: title, name: "twitter:title" }],
      ["meta", { content: pageDescription, name: "twitter:description" }],
    ];
  },
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
      { text: "Get started", link: routes.guide.gettingStarted },
      {
        text: "Guides",
        items: guideItems,
      },
      { text: "Coding agents", link: routes.guide.codingAgents },
      { text: "Reference", items: referenceItems },
    ],
    outline: [2, 3],
    search: { provider: "local" },
    sidebar: {
      [routes.guideRoot]: [
        {
          text: "Guides",
          collapsed: false,
          items: [
            ...guideItems,
            { text: "Author with a coding agent", link: routes.guide.codingAgents },
          ],
        },
      ],
      [routes.referenceRoot]: [
        {
          text: "Reference",
          collapsed: false,
          items: referenceItems,
        },
      ],
    },
    siteTitle: false,
    socialLinks: [{ icon: "github", link: repository }],
  },
  vite: viteConfig,
});
