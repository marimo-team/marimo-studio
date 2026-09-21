import type { ProjectionRequest } from "../src/projections.ts";
import type { Starter } from "../src/provider-catalog.ts";
import type { RuntimeConfig } from "../src/runtime-config.ts";
import type { ViewBuildState } from "../src/view-project.ts";

export const projectionRequest = (
  target: string,
  instanceId = `projection-${target}`,
): ProjectionRequest => ({
  siteId: `site:${target}`,
  instanceId,
  target,
});

export const starter: Starter = {
  schema: 1,
  id: "marimo-studio/vanilla:default",
  provider: "marimo-studio/vanilla",
  title: "HTML",
  summary: "One browser-native document.",
  documents: ["index.html"],
  availability: {
    available: true,
    version: null,
    reason: null,
    action: null,
  },
};

export const componentStarter: Starter = {
  ...starter,
  id: "acme-views/component:default",
  provider: "acme-views/component",
  title: "Component project",
  documents: ["src/App.tsx", "src/index.html"],
};

export const unbuiltView: ViewBuildState = {
  schema: 1,
  profile: "development",
  phase: "unbuilt",
  project_revision: null,
  artifact_revision: null,
  diagnostics: [],
  duration_ms: null,
};

export const symbolicRuntimeFields: Pick<
  RuntimeConfig,
  "projectionTargets" | "projectionPolicy" | "mounts" | "runtimeBindings"
> = {
  projectionTargets: {
    cells: {
      plot: {
        status: "ready",
        producer: "cell:v1:context",
        dependencyClosure: ["cell:v1:context"],
      },
    },
    variables: {
      context: {
        status: "ready",
        producer: "cell:v1:context",
        dependencyClosure: ["cell:v1:context"],
      },
    },
  },
  mounts: [
    {
      id: "site:plot",
      kind: "cell",
      source: { path: "src/index.html", line: 1, column: 1 },
      allowedTargets: ["plot"],
    },
  ],
  projectionPolicy: {
    maxActiveInstances: 512,
    maxUniqueCellTargets: 256,
    maxUniqueOutputTargets: 100,
    maxUniqueValueTargets: 100,
    maxTargetBytes: 4_096,
    maxPathSteps: 64,
    maxInstanceIdBytes: 256,
  },
  runtimeBindings: { cellRefs: { "cell:v1:context": "context-cell-id" } },
};
