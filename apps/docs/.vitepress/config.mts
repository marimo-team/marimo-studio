import { fileURLToPath } from "node:url";
import { defineConfig, type HeadConfig, type Plugin, type UserConfig } from "vitepress";
import llmstxt from "vitepress-plugin-llms";

import {
  authoringItems,
  deliveryItems,
  exampleItems,
  headIcons,
  introductionItems,
  normalizeBasePath,
  projectItems,
  referenceItems,
  routes,
  startItems,
  withBasePath,
} from "./routes.ts";

const repository = "https://github.com/marimo-team/marimo-studio";
const siteUrl = new URL("https://marimo-team.github.io/marimo-studio/");
const socialImage = new URL("og.png", siteUrl).href;
const socialDescription =
  "Build multiple custom web views from one marimo notebook with modern web tools and coding agents.";
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
  sitemap: { hostname: siteUrl.href },
  srcDir: "../../docs",
  title: "Marimo Studio",
  transformHead({ description, page, title }): HeadConfig[] {
    const canonical = canonicalUrl(page);
    const pageDescription = description || socialDescription;

    return [
      ["link", { href: canonical, rel: "canonical" }],
      ["meta", { property: "og:type", content: "website" }],
      ["meta", { property: "og:site_name", content: "Marimo Studio" }],
      ["meta", { property: "og:locale", content: "en_US" }],
      ["meta", { property: "og:title", content: title }],
      ["meta", { property: "og:description", content: pageDescription }],
      ["meta", { property: "og:url", content: canonical }],
      ["meta", { property: "og:image", content: socialImage }],
      ["meta", { property: "og:image:width", content: "2400" }],
      ["meta", { property: "og:image:height", content: "1260" }],
      [
        "meta",
        {
          property: "og:image:alt",
          content: "Notebook, view source, and Preview in Marimo Studio",
        },
      ],
      ["meta", { name: "twitter:title", content: title }],
      ["meta", { name: "twitter:description", content: pageDescription }],
      ["meta", { name: "twitter:image", content: socialImage }],
    ];
  },
  themeConfig: {
    editLink: {
      pattern: `${repository}/edit/main/docs/:path`,
      text: "Edit this page on GitHub",
    },
    footer: {
      message:
        'marimo-studio is a collaboration of <a class="studio-footer-link" href="https://marimo.io/">Marimo Team</a>, <a class="studio-footer-link" href="https://ivia.ethz.ch/">ETH Zurich IVIA Lab</a>, and <a class="studio-footer-link" href="https://dig.cmu.edu/team">CMU Data Interaction Group</a>',
    },
    logo: {
      alt: "Marimo Studio",
      dark: "/brand/marimo-studio-lockup-horizontal-dark.svg",
      light: "/brand/marimo-studio-lockup-horizontal-light.svg",
    },
    nav: [
      { text: "Overview", link: routes.whatIsStudio },
      { text: "Guide", link: routes.guide.index },
      { text: "Examples", link: routes.examples.index },
      { text: "Reference", link: routes.reference.index },
      { text: "Project", items: projectItems },
    ],
    outline: [2, 3],
    search: { provider: "local" },
    sidebar: {
      [routes.home]: [
        {
          text: "Introduction",
          collapsed: false,
          items: introductionItems,
        },
        {
          text: "Start",
          collapsed: false,
          items: startItems,
        },
        {
          text: "Author",
          collapsed: false,
          items: authoringItems,
        },
        {
          text: "Deliver",
          collapsed: true,
          items: deliveryItems,
        },
        { text: "Examples", link: routes.examples.index },
        { text: "Reference", link: routes.reference.index },
      ],
      [routes.examplesRoot]: [
        {
          text: "Examples",
          collapsed: false,
          items: exampleItems,
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
