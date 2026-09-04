import type { RuntimeConfig } from "@marimo-studio/protocol/runtime-config";

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
  },
  rootUrl: "/",
  publicRootUrl: "/",
  documentRootUrl: "/",
  supportUrl: "/_marimo-studio/views/dashboard",
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
  mounts: [
    {
      id: "value-report",
      kind: "value",
      source: { path: "index.html", line: 1, column: 1 },
      allowedTargets: ["report"],
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
