import { fileURLToPath } from "node:url";
import { defineConfig, type HeadConfig } from "vitepress";

const repository = "https://github.com/marimo-team/marimo-studio";
const siteUrl = new URL("https://marimo-team.github.io/marimo-studio/");
const socialDescription =
  "Create focused views with plain HTML and CSS that you and your coding agent already write. Marimo keeps notebook logic, controls, and outputs live.";
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
      { text: "Overview", link: "/how-it-works" },
      {
        text: "Guide",
        items: [
          { text: "Create your first view", link: "/getting-started" },
          { text: "Create and manage views", link: "/views" },
          { text: "Design a view", link: "/design-views" },
          { text: "Run and share views", link: "/share-views" },
        ],
      },
      { text: "Examples", link: "/examples" },
      { text: "Reference", link: "/reference" },
    ],
    outline: [2, 3],
    search: { provider: "local" },
    sidebar: [
      {
        text: "Introduction",
        collapsed: false,
        items: [
          { text: "Marimo Studio", link: "/" },
          { text: "Overview", link: "/how-it-works" },
          { text: "Create your first view", link: "/getting-started" },
        ],
      },
      {
        text: "Guide",
        collapsed: false,
        items: [
          { text: "Create and manage views", link: "/views" },
          { text: "Design a view", link: "/design-views" },
          { text: "Run and share views", link: "/share-views" },
        ],
      },
      {
        text: "Examples",
        link: "/examples",
      },
      {
        text: "Reference",
        collapsed: false,
        items: [
          { text: "Reference overview", link: "/reference" },
          { text: "CLI", link: "/cli" },
          { text: "Notebook configuration", link: "/configuration" },
          { text: "View document API", link: "/view-api" },
          { text: "Python API", link: "/python-api" },
        ],
      },
    ],
    siteTitle: false,
    socialLinks: [{ icon: "github", link: repository }],
  },
  vite: { publicDir },
});
