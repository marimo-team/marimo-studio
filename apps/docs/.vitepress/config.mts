import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, type HeadConfig, type Plugin, type UserConfig } from "vitepress";
import llmstxt from "vitepress-plugin-llms";

import {
  exampleItems,
  guideItems,
  headIcons,
  normalizeBasePath,
  redirects,
  referenceItems,
  routes,
  withBasePath,
} from "./routes.ts";

const repository = "https://github.com/marimo-team/marimo-studio";
const siteUrl = new URL("https://marimo-team.github.io/marimo-studio/");
const socialDescription =
  "Create custom web views from one reactive Marimo notebook with any frontend toolchain.";
const basePath = normalizeBasePath(process.env.BASE_PATH);
const publicDir = fileURLToPath(new URL("../public", import.meta.url));
const publicPath = (path: string): string => withBasePath(basePath, path);
const escapeAttribute = (value: string): string =>
  value.replaceAll("&", "&amp;").replaceAll('"', "&quot;").replaceAll("<", "&lt;");
const redirectDocument = (target: string): string => {
  const href = publicPath(target);
  const attribute = escapeAttribute(href);
  const scriptTarget = JSON.stringify(href);
  return [
    '<!doctype html><html lang="en"><head><meta charset="utf-8">',
    '<meta http-equiv="refresh" content="0;url=',
    attribute,
    '"><link rel="canonical" href="',
    attribute,
    '"><script>location.replace(',
    scriptTarget,
    "+location.search+location.hash)</script></head><body>",
    '<a href="',
    attribute,
    '">Continue to the current documentation.</a></body></html>',
  ].join("");
};
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
  async buildEnd(site) {
    await Promise.all(
      Object.entries(redirects).map(async ([source, target]) => {
        const output = join(site.outDir, source + ".html");
        await mkdir(dirname(output), { recursive: true });
        await writeFile(output, redirectDocument(target), "utf8");
      }),
    );
  },
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
      { text: "Overview", link: routes.overview },
      {
        text: "Guide",
        items: guideItems,
      },
      { text: "Examples", link: routes.examples.index },
      { text: "Reference", link: routes.reference.index },
    ],
    outline: [2, 3],
    search: { provider: "local" },
    sidebar: {
      [routes.guide.index]: [
        {
          text: "Guide",
          collapsed: false,
          items: guideItems,
        },
      ],
      [routes.examples.index]: [
        {
          text: "Examples",
          collapsed: false,
          items: exampleItems,
        },
      ],
      [routes.reference.index]: [
        {
          text: "Reference",
          collapsed: false,
          items: referenceItems,
        },
      ],
      [routes.home]: [
        {
          text: "Introduction",
          collapsed: false,
          items: [
            { text: "Marimo Studio", link: routes.home },
            { text: "Overview", link: routes.overview },
            { text: "Create your first view", link: routes.guide.gettingStarted },
          ],
        },
        {
          text: "Guide",
          collapsed: true,
          items: guideItems.filter((item) => item.link !== routes.guide.gettingStarted),
        },
        {
          text: "Examples",
          collapsed: true,
          items: exampleItems,
        },
        {
          text: "Reference",
          collapsed: true,
          items: referenceItems,
        },
      ],
    },
    siteTitle: false,
    socialLinks: [{ icon: "github", link: repository }],
  },
  vite: viteConfig,
});
