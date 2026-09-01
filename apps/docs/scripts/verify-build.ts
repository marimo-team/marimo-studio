import { readFile, stat } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { headIcons, normalizeBasePath, siteRoutes, withBasePath } from "../.vitepress/routes.ts";
import { documentationDefaultExamplePaths, documentationExampleFamilies } from "../examples.ts";

const packageRoot = dirname(fileURLToPath(new URL("../package.json", import.meta.url)));
const distDir = resolve(process.argv[2] ?? join(packageRoot, ".vitepress", "dist"));
const basePath = normalizeBasePath(process.env.BASE_PATH);
const failures: string[] = [];

const check = (condition: boolean, message: string): void => {
  if (!condition) {
    failures.push(message);
  }
};

const isFile = async (path: string): Promise<boolean> => {
  try {
    return (await stat(path)).isFile();
  } catch {
    return false;
  }
};

const outputPath = (route: string): string => {
  const path = route.replace(/^\//, "");
  if (!path) {
    return join(distDir, "index.html");
  }
  if (path.endsWith("/")) {
    return join(distDir, path, "index.html");
  }
  return join(distDir, `${path}.html`);
};

const builtDocuments: string[] = [];
check(new Set(siteRoutes).size === siteRoutes.length, "Route inventory contains duplicate paths.");

for (const route of siteRoutes) {
  const path = outputPath(route);
  if (await isFile(path)) {
    builtDocuments.push(await readFile(path, "utf8"));
  } else {
    failures.push(`Missing built route: ${route}`);
  }
}

const indexPath = outputPath("/");
if (await isFile(indexPath)) {
  const index = await readFile(indexPath, "utf8");
  const assetReferences = [
    ...index.matchAll(/\b(?:href|src)="([^"]*\/(?:assets|brand|icons)\/[^"#?]+)"/g),
  ].map((match) => match[1]);

  check(
    assetReferences.some((reference) => reference?.startsWith(withBasePath(basePath, "/assets/"))),
    `Missing generated asset reference under ${withBasePath(basePath, "/assets/")}`,
  );
  check(
    index.includes(`href="${withBasePath(basePath, "/assets/")}`),
    `Missing generated stylesheet under ${withBasePath(basePath, "/assets/")}`,
  );
  check(
    index.includes(`src="${withBasePath(basePath, "/assets/")}`),
    `Missing generated script under ${withBasePath(basePath, "/assets/")}`,
  );
  check(
    assetReferences.every((reference) => reference?.startsWith(`${basePath}/`)),
    `Built asset reference escapes the configured base path ${basePath || "/"}.`,
  );

  for (const iconPath of Object.values(headIcons)) {
    const href = withBasePath(basePath, iconPath);
    check(index.includes(`href="${href}"`), `Missing head icon reference: ${href}`);
  }
}

const renderedSite = builtDocuments.join("\n");
for (const route of siteRoutes) {
  const href = withBasePath(basePath, route);
  check(renderedSite.includes(`href="${href}"`), `Missing base-aware navigation link: ${href}`);
}

let exampleCount = 0;
let notebookCount = 0;
for (const family of documentationExampleFamilies) {
  notebookCount += 1;
  const notebookEntry = join(distDir, "examples", family.slug, "notebook", "index.html");
  if (await isFile(notebookEntry)) {
    const notebookDocument = await readFile(notebookEntry, "utf8");
    check(
      notebookDocument.includes("<marimo-code hidden"),
      `Missing source in static notebook export: ${family.slug}`,
    );
    check(
      notebookDocument.includes(
        `<marimo-filename hidden>${family.notebook.split("/").at(-1)}</marimo-filename>`,
      ),
      `Missing filename in static notebook export: ${family.slug}`,
    );
  } else {
    failures.push(`Missing static notebook export: ${family.slug}`);
  }

  for (const view of family.views) {
    exampleCount += 1;
    const root = join(distDir, "examples", family.slug, view.key);
    const entrypoint = join(root, "index.html");
    const config = join(root, "_marimo-studio", "views", view.key, "config");
    const runtime = join(root, "_marimo-studio", "assets", "runtime.js");
    const noJekyll = join(root, ".nojekyll");

    if (!(await isFile(entrypoint))) {
      failures.push(`Missing live example entrypoint: ${family.slug}/${view.key}`);
      continue;
    }
    check(await isFile(config), `Missing live example config: ${family.slug}/${view.key}`);
    check(await isFile(runtime), `Missing live example runtime: ${family.slug}/${view.key}`);
    check(await isFile(noJekyll), `Missing live example .nojekyll: ${family.slug}/${view.key}`);

    const document = await readFile(entrypoint, "utf8");
    check(
      document.includes('<base href="./">'),
      `Missing relative document base: ${family.slug}/${view.key}`,
    );
    check(
      document.includes(`"supportUrl":"./_marimo-studio/views/${view.key}"`),
      `Missing relative support URL: ${family.slug}/${view.key}`,
    );
    check(
      !/\b(?:href|src)="\/(?!\/)/.test(document),
      `Root-absolute example asset escapes the deployment base: ${family.slug}/${view.key}`,
    );

    for (const match of document.matchAll(/\bhref="(\.\.\/[^"?#]+\/index\.html)"/g)) {
      const target = match[1];
      if (target) {
        check(
          await isFile(resolve(dirname(entrypoint), target)),
          `Missing sibling example linked from ${family.slug}/${view.key}: ${target}`,
        );
      }
    }
  }
}

for (const path of documentationDefaultExamplePaths) {
  const href = withBasePath(basePath, path);
  check(renderedSite.includes(`href="${href}"`), `Missing base-aware example link: ${href}`);
}

for (const generated of ["llms.txt", "llms-full.txt", "robots.txt", "sitemap.xml"]) {
  check(
    await isFile(join(distDir, generated)),
    `Missing generated documentation file: ${generated}`,
  );
}

const sitemapPath = join(distDir, "sitemap.xml");
if (await isFile(sitemapPath)) {
  const sitemap = await readFile(sitemapPath, "utf8");
  for (const route of siteRoutes) {
    const cleanRoute = route === "/" ? "" : route.replace(/^\//, "");
    const canonical = new URL(cleanRoute, "https://marimo-team.github.io/marimo-studio/").href;
    check(sitemap.includes(`<loc>${canonical}</loc>`), `Sitemap is missing route: ${canonical}`);
  }
}

if (failures.length > 0) {
  console.error(
    `Documentation build verification failed:\n${failures.map((failure) => `- ${failure}`).join("\n")}`,
  );
  process.exitCode = 1;
} else {
  console.log(
    `Verified ${siteRoutes.length} documentation routes, ${notebookCount} static notebooks, and ${exampleCount} live views.`,
  );
}
