import type { ProjectionKind } from "@marimo-studio/protocol/projections";
import type { RuntimeConfig } from "@marimo-studio/protocol/runtime-config";

import type { RuntimeProjectionRequest } from "../src/projections/resolution.ts";

const projectionRevisionFor = (value: string): string => {
  const hash = value
    .split("")
    .reduce(
      (current, character) => Math.imul(current ^ character.charCodeAt(0), 16_777_619),
      2_166_136_261,
    );
  return (hash >>> 0).toString(16).padStart(8, "0").repeat(8);
};

export const projectionRequest = (
  target: string,
  kind: ProjectionKind,
  instanceId = `projection-${target}`,
): RuntimeProjectionRequest => ({
  siteId: `site:${kind}:${target}`,
  instanceId,
  kind,
  target,
});

export const symbolicRuntimeFields: Pick<
  RuntimeConfig,
  "projectionRevision" | "projectionTargets" | "projectionPolicy" | "mounts" | "runtimeBindings"
> = {
  projectionRevision: projectionRevisionFor("empty"),
  projectionTargets: {
    cells: {},
    variables: {},
  },
  mounts: [],
  projectionPolicy: {
    maxActiveInstances: 512,
    maxUniqueCellTargets: 256,
    maxUniqueOutputTargets: 100,
    maxUniqueValueTargets: 100,
    maxTargetBytes: 4_096,
    maxPathSteps: 64,
    maxInstanceIdBytes: 256,
  },
  runtimeBindings: { cellRefs: {} },
};

export const runtimeConfig = (overrides: Partial<RuntimeConfig> = {}): RuntimeConfig => ({
  schema: 1,
  revision: "presentation-revision",
  view: "dashboard",
  views: ["dashboard"],
  runtime: {
    id: "server",
    instance: "server-instance",
    available: ["server", "wasm"],
    data: {
      fileKey: "/workspace/notebook.py",
      capabilityToken: "presentation-capability",
      sessionId: "s_abc123",
      serverInstance: "server-instance",
      preserveSession: false,
      url: "/proxy/app/",
    },
  },
  rootUrl: "/proxy/app/",
  publicRootUrl: "/proxy/app/",
  documentRootUrl: "/proxy/app/",
  supportUrl: "/proxy/app/_marimo-studio/views/dashboard",
  presentationSessionId: "s_view01",
  showCellLogs: true,
  ...symbolicRuntimeFields,
  diagnostics: [],
  appConfig: {},
  userConfig: {},
  configOverrides: {},
  dev: true,
  mode: "edit",
  ...overrides,
});

export const projectionRuntimeConfig = (
  requests: readonly RuntimeProjectionRequest[],
): RuntimeConfig => {
  const variables = Array.from(
    new Set(
      requests
        .filter((request) => request.kind !== "cell")
        .map((request) => request.target.split(/[.[]/, 1)[0]),
    ),
  );
  return runtimeConfig({
    projectionRevision: projectionRevisionFor(JSON.stringify(requests)),
    projectionTargets: {
      cells: {},
      variables: Object.fromEntries(
        variables.map((variable) => [
          variable,
          {
            status: "ready",
            producer: `cell:v1:${variable}`,
            dependencyClosure: [`cell:v1:${variable}`],
          },
        ]),
      ),
    },
    mounts: requests.map((request, index) => ({
      id: request.siteId,
      kind: request.kind,
      source: { path: "src/App.tsx", line: index + 1, column: 1 },
      allowedTargets: [request.target],
    })),
    runtimeBindings: {
      cellRefs: Object.fromEntries(
        variables.map((variable) => [`cell:v1:${variable}`, `${variable}-cell`]),
      ),
    },
  });
};
