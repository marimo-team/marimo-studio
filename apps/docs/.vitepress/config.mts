import { fileURLToPath } from "node:url";
import { defineConfig, type HeadConfig, type Plugin } from "vitepress";
import llmstxt from "vitepress-plugin-llms";

const repository = "https://github.com/marimo-team/marimo-studio";
const siteUrl = new URL("https://marimo-team.github.io/marimo-studio/");
const socialDescription =
  "Keep analytical context in one reactive, reproducible Marimo notebook, then shape a custom web view for each audience.";
const socialImageAlt = "Marimo Studio: Tune your notebook for every audience.";
const socialImageUrl = new URL("og.png", siteUrl).href;
const baseName = process.env.BASE_PATH?.trim().replace(/^\/+|\/+$/g, "");
const basePath = baseName ? `/${baseName}` : "";
const publicDir = fileURLToPath(new URL("../public", import.meta.url));
const publicPath = (path: string): string => `${basePath}${path}`;
const canonicalUrl = (page: string): string => {
  const route = page
    .replace(/^\/+/, "")
    .replace(/(^|\/)index\.md$/, "$1")
    .replace(/\.md$/, "");
  return new URL(route, siteUrl).href;
};

export default defineConfig({
  base: basePath ? `${basePath}/` : "/",
  cleanUrls: true,
  description: socialDescription,
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
      ["meta", { content: socialImageUrl, property: "og:image" }],
      ["meta", { content: socialImageUrl, property: "og:image:secure_url" }],
      ["meta", { content: "image/png", property: "og:image:type" }],
      ["meta", { content: "2400", property: "og:image:width" }],
      ["meta", { content: "1260", property: "og:image:height" }],
      ["meta", { content: socialImageAlt, property: "og:image:alt" }],
      ["meta", { content: "summary_large_image", name: "twitter:card" }],
      ["meta", { content: title, name: "twitter:title" }],
      ["meta", { content: pageDescription, name: "twitter:description" }],
      ["meta", { content: socialImageUrl, name: "twitter:image" }],
      ["meta", { content: socialImageAlt, name: "twitter:image:alt" }],
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
      { text: "Overview", link: "/overview" },
      {
        text: "Guide",
        items: [
          { text: "Guide overview", link: "/guide/" },
          { text: "Create your first view", link: "/guide/getting-started" },
          { text: "Create and manage views", link: "/guide/views" },
          { text: "Use notebook results", link: "/guide/notebook-results" },
          { text: "Author with the live workspace", link: "/guide/live-authoring" },
          { text: "Use HTML, CSS, and JavaScript", link: "/guide/web-platform" },
          { text: "Agent-native authoring", link: "/guide/coding-agents" },
          { text: "Run, export, and share", link: "/guide/run-and-share" },
        ],
      },
      { text: "Examples", link: "/examples/" },
      { text: "Reference", link: "/reference/" },
    ],
    outline: [2, 3],
    search: { provider: "local" },
    sidebar: {
      "/guide/": [
        {
          text: "Guide",
          collapsed: false,
          items: [
            { text: "Guide overview", link: "/guide/" },
            { text: "Create your first view", link: "/guide/getting-started" },
            { text: "Create and manage views", link: "/guide/views" },
            { text: "Use notebook results", link: "/guide/notebook-results" },
            { text: "Author with the live workspace", link: "/guide/live-authoring" },
            { text: "Use HTML, CSS, and JavaScript", link: "/guide/web-platform" },
            { text: "Agent-native authoring", link: "/guide/coding-agents" },
            { text: "Run, export, and share", link: "/guide/run-and-share" },
          ],
        },
      ],
      "/examples/": [
        {
          text: "Examples",
          collapsed: false,
          items: [
            { text: "Examples overview", link: "/examples/" },
            { text: "Revenue forecast", link: "/examples/revenue-forecast" },
            { text: "Collection research", link: "/examples/collection-research" },
          ],
        },
      ],
      "/reference/": [
        {
          text: "Reference",
          collapsed: false,
          items: [
            { text: "Reference overview", link: "/reference/" },
            { text: "View document API", link: "/reference/view-document" },
            { text: "Agent API", link: "/reference/agent-api" },
            { text: "CLI", link: "/reference/cli" },
            { text: "Notebook configuration", link: "/reference/configuration" },
            { text: "Runtime behavior", link: "/reference/runtimes" },
            { text: "Python API", link: "/reference/python-api" },
          ],
        },
      ],
      "/": [
        {
          text: "Introduction",
          collapsed: false,
          items: [
            { text: "Marimo Studio", link: "/" },
            { text: "Overview", link: "/overview" },
            { text: "Create your first view", link: "/guide/getting-started" },
          ],
        },
        {
          text: "Guide",
          collapsed: true,
          items: [
            { text: "Guide overview", link: "/guide/" },
            { text: "Create and manage views", link: "/guide/views" },
            { text: "Use notebook results", link: "/guide/notebook-results" },
            { text: "Author with the live workspace", link: "/guide/live-authoring" },
            { text: "Use HTML, CSS, and JavaScript", link: "/guide/web-platform" },
            { text: "Agent-native authoring", link: "/guide/coding-agents" },
            { text: "Run, export, and share", link: "/guide/run-and-share" },
          ],
        },
        {
          text: "Examples",
          collapsed: true,
          items: [
            { text: "Examples overview", link: "/examples/" },
            { text: "Revenue forecast", link: "/examples/revenue-forecast" },
            { text: "Collection research", link: "/examples/collection-research" },
          ],
        },
        {
          text: "Reference",
          collapsed: true,
          items: [
            { text: "Reference overview", link: "/reference/" },
            { text: "View document API", link: "/reference/view-document" },
            { text: "Agent API", link: "/reference/agent-api" },
            { text: "CLI", link: "/reference/cli" },
            { text: "Notebook configuration", link: "/reference/configuration" },
            { text: "Runtime behavior", link: "/reference/runtimes" },
            { text: "Python API", link: "/reference/python-api" },
          ],
        },
      ],
    },
    siteTitle: false,
    socialLinks: [{ icon: "github", link: repository }],
  },
  vite: {
    plugins: [
      llmstxt({
        domain: siteUrl.href.replace(/\/$/, ""),
        excludeIndexPage: false,
      }) as unknown as Plugin,
    ],
    publicDir,
  },
});
