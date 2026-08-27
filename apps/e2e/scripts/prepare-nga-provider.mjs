import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

import {
  providerNotebookFixturePath,
  providerNotebookPath,
  externalProviderNotebookFixture,
  externalProviderNotebookPath,
  providerStaticRoot,
  providerWorkspaceDirectory,
  repositoryDirectory,
} from "./paths.mjs";

const sourceViews = resolve(repositoryDirectory, "examples/__marimo__/studio/nga");
const targetViews = resolve(providerWorkspaceDirectory, "__marimo__/studio/nga");
const removeTree = (directory) =>
  rm(directory, {
    force: true,
    maxRetries: 10,
    recursive: true,
    retryDelay: 100,
  });

export const clearNgaProviderGeneratedState = async () => {
  for (const view of ["overview", "gallery", "story"]) {
    await removeTree(resolve(targetViews, view, ".artifacts"));
  }
  await removeTree(resolve(targetViews, ".locks"));
};

const replaceRequired = (source, before, after, label) => {
  const first = source.indexOf(before);
  if (first < 0 || source.indexOf(before, first + before.length) >= 0) {
    throw new Error(`Canonical NGA ${label} marker must occur exactly once`);
  }
  return source.replace(before, after);
};

const patchReact = (source) => {
  let patched = replaceRequired(
    source,
    'import React, { useMemo, useState } from "react";',
    'import React, { useEffect, useMemo, useState } from "react";',
    "React import",
  );
  patched = replaceRequired(
    patched,
    "const CHARTS = [",
    `type ProjectionAcceptance = {
  readonly framework: "React";
  readonly initial: string;
  readonly alternate: string;
  readonly siteId: string;
  retarget(target: string): void;
  unmount(): void;
  mount(target: string): void;
};

declare global {
  var __ngaProjectionAcceptance: ProjectionAcceptance | undefined;
}

const CHARTS = [`,
    "React acceptance type",
  );
  patched = replaceRequired(
    patched,
    "  const [chartIndex, setChartIndex] = useState(0);",
    `  const [chartIndex, setChartIndex] = useState(0);
  const [projectionTarget, setProjectionTarget] = useState<string | null | undefined>(undefined);`,
    "React projection state",
  );
  patched = replaceRequired(
    patched,
    "  const activeChart = CHARTS[chartIndex];",
    `  const activeChart = CHARTS[chartIndex];
  const activeProjectionTarget = projectionTarget === undefined
    ? activeChart.name
    : projectionTarget;

  useEffect(() => {
    const bridge: ProjectionAcceptance = {
      framework: "React",
      initial: CHARTS[0].name,
      alternate: CHARTS[1].name,
      get siteId() {
        const siteId = document
          .querySelector(".chart-workspace marimo-cell")
          ?.getAttribute("data-marimo-studio-site");
        if (!siteId) throw new Error("React projection site is unavailable");
        return siteId;
      },
      retarget: (target) => setProjectionTarget(target),
      unmount: () => setProjectionTarget(null),
      mount: (target) => setProjectionTarget(target),
    };
    globalThis.__ngaProjectionAcceptance = bridge;
    return () => {
      if (globalThis.__ngaProjectionAcceptance === bridge) {
        delete globalThis.__ngaProjectionAcceptance;
      }
    };
  }, []);`,
    "React acceptance bridge",
  );
  return replaceRequired(
    patched,
    '        <marimo-cell name={activeChart.name} data-marimo-allow="*" />',
    `        {activeProjectionTarget === null
          ? null
          : <marimo-cell name={activeProjectionTarget} data-marimo-allow="*" />}`,
    "React dynamic host",
  );
};

const patchSvelte = (source) => {
  let patched = replaceRequired(
    source,
    "  ];\n\n  let artworks = $state<Artwork[]>([]);",
    `  ];

  type ProjectionAcceptance = {
    readonly framework: "Svelte";
    readonly initial: string;
    readonly alternate: string;
    readonly siteId: string;
    retarget(target: string): void;
    unmount(): void;
    mount(target: string): void;
  };
  const acceptanceGlobal = globalThis as typeof globalThis & {
    __ngaProjectionAcceptance?: ProjectionAcceptance;
  };
  let projectionTarget = $state<string | null>(chapters[0].name);
  let projectionChapters = $derived(
    projectionTarget === null
      ? []
      : [{ ...chapters[0], number: "acceptance", name: projectionTarget }],
  );
  $effect(() => {
    const bridge: ProjectionAcceptance = {
      framework: "Svelte",
      initial: chapters[0].name,
      alternate: chapters[1].name,
      get siteId() {
        const siteId = document
          .querySelector(".chapter-result marimo-cell")
          ?.getAttribute("data-marimo-studio-site");
        if (!siteId) throw new Error("Svelte projection site is unavailable");
        return siteId;
      },
      retarget: (target) => (projectionTarget = target),
      unmount: () => (projectionTarget = null),
      mount: (target) => (projectionTarget = target),
    };
    acceptanceGlobal.__ngaProjectionAcceptance = bridge;
    return () => {
      if (acceptanceGlobal.__ngaProjectionAcceptance === bridge) {
        delete acceptanceGlobal.__ngaProjectionAcceptance;
      }
    };
  });

  let artworks = $state<Artwork[]>([]);`,
    "Svelte acceptance state",
  );
  patched = replaceRequired(
    patched,
    "  {#each chapters as chapter}",
    "  {#each projectionChapters as chapter (chapter.number)}",
    "Svelte dynamic host",
  );
  return patched;
};

export const prepareNgaProviderWorkspace = async () => {
  await removeTree(providerWorkspaceDirectory);
  await removeTree(providerStaticRoot);
  await mkdir(providerWorkspaceDirectory, { recursive: true });
  await mkdir(providerStaticRoot, { recursive: true });
  await mkdir(resolve(targetViews, ".."), { recursive: true });
  await cp(providerNotebookFixturePath, providerNotebookPath);
  await cp(externalProviderNotebookFixture, externalProviderNotebookPath);
  await cp(sourceViews, targetViews, { recursive: true });

  await clearNgaProviderGeneratedState();
  const reactPath = resolve(targetViews, "gallery/src/App.tsx");
  const sveltePath = resolve(targetViews, "story/src/App.svelte");
  await writeFile(reactPath, patchReact(await readFile(reactPath, "utf8")), "utf8");
  await writeFile(sveltePath, patchSvelte(await readFile(sveltePath, "utf8")), "utf8");

  return {
    notebook: providerNotebookPath,
    staticRoot: providerStaticRoot,
    workspace: providerWorkspaceDirectory,
  };
};

export const cleanNgaProviderWorkspace = () =>
  Promise.all(
    [providerWorkspaceDirectory, providerStaticRoot].map((directory) => removeTree(directory)),
  );
