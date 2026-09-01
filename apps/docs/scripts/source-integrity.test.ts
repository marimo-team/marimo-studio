import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, extname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vite-plus/test";

import { siteRoutes } from "../.vitepress/routes.ts";

const packageRoot = dirname(fileURLToPath(new URL("../package.json", import.meta.url)));
const repositoryRoot = resolve(packageRoot, "../..");
const docsRoot = resolve(packageRoot, "../../docs");

const markdownFiles = (directory: string): string[] =>
  readdirSync(directory)
    .sort()
    .flatMap((entry) => {
      const path = join(directory, entry);
      if (statSync(path).isDirectory()) {
        return markdownFiles(path);
      }
      return entry.endsWith(".md") ? [path] : [];
    });

const routeForFile = (file: string): string => {
  const source = relative(docsRoot, file).replaceAll("\\", "/");
  if (source === "index.md") {
    return "/";
  }
  if (source.endsWith("/index.md")) {
    return `/${source.slice(0, -"index.md".length)}`;
  }
  return `/${source.slice(0, -".md".length)}`;
};

const withoutCodeFences = (source: string): string => source.replaceAll(/```[\s\S]*?```/g, "");

const slugify = (heading: string): string =>
  heading
    .normalize("NFKD")
    .replaceAll(/[`'"<>]/g, "")
    .replaceAll(/[^\p{Letter}\p{Number}]+/gu, "-")
    .replaceAll(/-{2,}/g, "-")
    .replaceAll(/^-+|-+$/g, "")
    .toLowerCase();

const anchors = (file: string): Set<string> =>
  new Set(
    Array.from(withoutCodeFences(readFileSync(file, "utf8")).matchAll(/^#{1,6}\s+(.+?)\s*$/gm)).map(
      (match) => slugify(match[1] ?? ""),
    ),
  );

const resolveTarget = (sourceFile: string, href: string): string | undefined => {
  const pathname = decodeURIComponent(href.split("#")[0]?.split("?")[0] ?? "");
  if (!pathname) {
    return sourceFile;
  }
  const base = pathname.startsWith("/")
    ? join(docsRoot, pathname)
    : resolve(dirname(sourceFile), pathname);
  const candidates = extname(base) ? [base] : [base, `${base}.md`, join(base, "index.md")];
  return candidates.find((path) => existsSync(path));
};

describe("documentation source integrity", () => {
  const files = markdownFiles(docsRoot);

  it("gives every public page a title and description", () => {
    const failures = files.flatMap((file) => {
      const source = readFileSync(file, "utf8");
      const name = relative(docsRoot, file);
      const missing: string[] = [];
      if (!source.startsWith("---\n") || !/^title:\s+\S/m.test(source)) {
        missing.push(`${name}: missing frontmatter title`);
      }
      if (!/^description:\s+\S/m.test(source)) {
        missing.push(`${name}: missing frontmatter description`);
      }
      return missing;
    });
    expect(failures).toEqual([]);
  });

  it("keeps current release pins aligned across public surfaces", () => {
    const manifest = readFileSync(
      join(repositoryRoot, "packages", "marimo-studio", "pyproject.toml"),
      "utf8",
    );
    const currentVersion = manifest.match(/^version = "([0-9]+\.[0-9]+\.[0-9]+)"$/m)?.[1];
    expect(currentVersion).toBeDefined();

    const surfaces = [
      join(repositoryRoot, "README.md"),
      join(repositoryRoot, "packages", "marimo-studio", "README.md"),
      join(repositoryRoot, "skills", "marimo-studio", "SKILL.md"),
      ...files,
    ];
    const failures: string[] = [];
    for (const file of surfaces) {
      const source = readFileSync(file, "utf8");
      for (const match of source.matchAll(
        /marimo-studio(?:\[deno\])?==([0-9]+\.[0-9]+\.[0-9]+)/g,
      )) {
        if (match[1] !== currentVersion) {
          failures.push(
            `${relative(repositoryRoot, file)}: expected ${currentVersion}, found ${match[1]}`,
          );
        }
      }
    }
    expect(failures).toEqual([]);
  });

  it("keeps every public page in the route inventory", () => {
    expect(new Set(siteRoutes)).toEqual(new Set(files.map(routeForFile)));
  });

  it("resolves every local Markdown link and heading fragment", () => {
    const failures: string[] = [];
    for (const sourceFile of files) {
      const source = withoutCodeFences(readFileSync(sourceFile, "utf8"));
      for (const match of source.matchAll(/!?\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g)) {
        const href = match[1] ?? "";
        if (/^(?:[a-z]+:|\/\/)/i.test(href)) {
          continue;
        }
        const target = resolveTarget(sourceFile, href);
        const sourceName = relative(docsRoot, sourceFile);
        if (!target) {
          failures.push(`${sourceName}: missing target ${href}`);
          continue;
        }
        const fragment = href.split("#")[1]?.split("?")[0];
        if (fragment && target.endsWith(".md") && !anchors(target).has(fragment)) {
          failures.push(`${sourceName}: missing heading #${fragment} in ${href}`);
        }
      }
    }
    expect(failures).toEqual([]);
  });
});
