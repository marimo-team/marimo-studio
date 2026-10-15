import type { RuntimeConfig } from "@marimo-studio/protocol/runtime-config";

import { createHash } from "node:crypto";

import type { PreparedProjectionResources } from "../src/prepared/index.ts";

export const preparedRuntimeConfig = {
  schema: 1,
  revision: "prepared-revision",
  projectionRevision: "a".repeat(64),
  view: "dashboard",
  views: ["dashboard"],
  runtime: {
    id: "zero-python",
    instance: "prepared-instance",
    data: {},
    urls: {},
  },
  rootUrl: "http://localhost:3000/",
  publicRootUrl: "http://localhost:3000/",
  documentRootUrl: "http://localhost:3000/",
  supportUrl: "http://localhost:3000/_marimo-studio/views/dashboard",
  projectionTargets: {
    cells: {},
    variables: {
      report: {
        status: "ready",
        producer: "cell:v1:report",
        dependencyClosure: ["cell:v1:report"],
      },
    },
  },
  sites: [
    {
      id: "value-report",
      kind: "value",
      source: { path: "index.html", line: 1, column: 1 },
      targets: ["report"],
      accept: [],
      size: null,
      render: null,
    },
  ],
  projectionPolicy: {
    maxActiveInstances: 512,
    maxUniqueCellTargets: 256,
    maxUniqueOutputTargets: 100,
    maxUniqueValueTargets: 100,
    maxTargetBytes: 4096,
    maxPathSteps: 64,
    maxInstanceIdBytes: 256,
  },
  runtimeBindings: { cellRefs: { "cell:v1:report": "report-cell" } },
  diagnostics: [],
  appConfig: {},
  userConfig: {},
  configOverrides: {},
  showCellLogs: true,
  dev: false,
  mode: "run",
} satisfies RuntimeConfig;

export const preparedResources = (): PreparedProjectionResources => ({
  files: {},
  modelNotifications: [],
  functions: {},
  uiValues: {},
});

export const projectionUiId = (ownerCellId: string, digest: string, sourceId: string): string =>
  `${ownerCellId}-projection-${digest.repeat(64)}-ui-${sourceId}`;

export const preparedPresentation = {
  appConfig: {},
  configOverrides: {},
  userConfig: {},
};

export const preparedTheme = {
  current: () => "light" as const,
  subscribe: () => () => {},
};

export const settlePreparedRender = async (): Promise<void> => {
  await new Promise((resolve) => setTimeout(resolve, 0));
};

const SITE_SOURCE = { path: "index.html", line: 1, column: 1 };

export const withHostSites = (
  config: RuntimeConfig,
  root: ParentNode = document,
): RuntimeConfig => {
  const sites = [...config.sites];
  const variables = { ...config.projectionTargets.variables };
  const cells = { ...config.projectionTargets.cells };
  const target = (producer: string) => ({
    status: "ready" as const,
    producer,
    dependencyClosure: [producer],
  });
  root.querySelectorAll("marimo-output[value], marimo-cell[name]").forEach((host) => {
    const kind = host.localName === "marimo-cell" ? "cell" : "output";
    const name = host.getAttribute(kind === "cell" ? "name" : "value") ?? "";
    const id = `site:${kind}:${name}`;
    host.setAttribute("data-marimo-studio-site", id);
    if (!sites.some((site) => site.id === id)) {
      sites.push({
        id,
        kind,
        source: SITE_SOURCE,
        targets: [name],
        accept: [],
        size: null,
        render: null,
      });
    }
    if (kind === "cell") {
      cells[name] ??= target(`cell:v1:${name}`);
    } else {
      const variable = name.split(/[.[]/u)[0] ?? name;
      variables[variable] ??= target(`cell:v1:${variable}`);
    }
  });
  // Site policy is keyed on the projection revision, so added sites need a new one.
  const projectionRevision = createHash("sha256")
    .update(sites.map(({ id }) => id).join("\0"))
    .digest("hex");
  return { ...config, projectionRevision, sites, projectionTargets: { cells, variables } };
};
