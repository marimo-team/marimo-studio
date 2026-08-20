import type { RuntimeConfig } from "@marimo-studio/protocol/runtime-config";

import type { PreparedProjectionResources } from "../src/prepared/index.ts";

const descriptor = {
  id: "prepared",
  label: "Prepared",
  description: "Prepared notebook results",
  execution: "prepared",
  projections: { cell: true, output: true, value: true },
  controls: "state",
  query: "state",
  preparation: "on-select",
  session: "none",
} as const;

export const preparedRuntimeConfig = {
  schema: 1,
  revision: "prepared-revision",
  view: "dashboard",
  views: ["dashboard"],
  runtime: {
    descriptor,
    instance: "prepared-instance",
    data: {},
  },
  rootUrl: "/",
  publicRootUrl: "/",
  documentRootUrl: "/",
  supportUrl: "/_marimo-studio/views/dashboard",
  cellBindings: {},
  valueBindings: {
    report: {
      variable: "report",
      cell: { kind: "id", value: "report-cell" },
    },
  },
  outputBindings: {},
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
