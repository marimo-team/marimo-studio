import { readFile, stat } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { headIcons, normalizeBasePath, siteRoutes, withBasePath } from "../.vitepress/routes.ts";

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

if (failures.length > 0) {
  console.error(
    `Documentation build verification failed:\n${failures.map((failure) => `- ${failure}`).join("\n")}`,
  );
  process.exitCode = 1;
} else {
  console.log(`Verified ${siteRoutes.length} documentation routes.`);
}
