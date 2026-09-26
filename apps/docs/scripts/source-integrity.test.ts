import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, extname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vite-plus/test";
import { createMarkdownRenderer } from "vitepress";

import { siteRoutes } from "../.vitepress/routes.ts";

const packageRoot = dirname(fileURLToPath(new URL("../package.json", import.meta.url)));
const docsRoot = resolve(packageRoot, "../../docs");
const markdownRenderer = createMarkdownRenderer(docsRoot);

interface PageEnvironment {
  frontmatter?: {
    title?: string;
    description?: string;
  };
}

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

  it("gives every public page a title and description", async () => {
    const markdown = await markdownRenderer;
    const failures = files.flatMap((file) => {
      const source = readFileSync(file, "utf8");
      const name = relative(docsRoot, file);
      const environment: PageEnvironment = {};
      markdown.parse(source, environment);
      const missing: string[] = [];
      if (!environment.frontmatter?.title?.trim()) {
        missing.push(`${name}: missing frontmatter title`);
      }
      if (!environment.frontmatter?.description?.trim()) {
        missing.push(`${name}: missing frontmatter description`);
      }
      return missing;
    });
    expect(failures).toEqual([]);
  });

  it("keeps every public page in the route inventory", () => {
    expect(new Set(siteRoutes)).toEqual(new Set(files.map(routeForFile)));
  });

  it("resolves local links and heading fragments", async () => {
    const markdown = await markdownRenderer;
    const pageAnchors = new Map(
      files.map((file) => [
        file,
        new Set(
          markdown
            .parse(readFileSync(file, "utf8"), {})
            .filter((token) => token.type === "heading_open")
            .map((token) => token.attrGet("id"))
            .filter((anchor): anchor is string => anchor !== null),
        ),
      ]),
    );
    const failures: string[] = [];
    for (const sourceFile of files) {
      const tokens = markdown.parse(readFileSync(sourceFile, "utf8"), {});
      const links = tokens
        .flatMap((token) => token.children ?? [])
        .filter(
          (token) => token.type === "link_open" && token.attrGet("class") !== "header-anchor",
        );
      for (const link of links) {
        const href = link.attrGet("href") ?? "";
        if (/^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(href)) {
          continue;
        }
        const target = resolveTarget(sourceFile, href);
        if (target === undefined) {
          failures.push(`${relative(docsRoot, sourceFile)}: missing local target ${href}`);
          continue;
        }
        if (!href.includes("#")) {
          continue;
        }
        if (!target.endsWith(".md")) {
          continue;
        }
        const fragment = decodeURIComponent(href.split("#")[1]?.split("?")[0] ?? "");
        if (!pageAnchors.get(target)?.has(fragment)) {
          failures.push(
            `${relative(docsRoot, sourceFile)}: missing heading #${fragment} in ${href}`,
          );
        }
      }
    }
    expect(failures).toEqual([]);
  });
});
