import type { Starter } from "@marimo-studio/protocol/provider-catalog";
import type { RuntimeConfig } from "@marimo-studio/protocol/runtime-config";
import type { ViewBuildState } from "@marimo-studio/protocol/view-project";
import type { ViewList } from "@marimo-studio/protocol/views";

export const emptyProjectionEvidence = {
  projectionInstances: [],
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

export const starter: Starter = {
  schema: 1,
  id: "marimo-studio/vanilla:default",
  provider: "marimo-studio/vanilla",
  title: "HTML",
  summary: "One browser-native document.",
  documents: ["index.html"],
  availability: { available: true, version: null, reason: null, action: null },
};

export const componentStarter: Starter = {
  ...starter,
  id: "acme-views/component:default",
  provider: "acme-views/component",
  title: "Component project",
  documents: ["src/App.tsx", "src/index.html"],
};

export const viewList = (
  names: readonly string[],
  defaultView = names[0] ?? "dashboard",
  starters: readonly Starter[] = [starter],
  defaultStarter = "marimo-studio/vanilla:default",
): ViewList => ({
  schema: 1,
  default_view: defaultView,
  default_starter: defaultStarter,
  views: names.map((name) => ({ name })),
  starters: [...starters],
});

export const symbolicRuntimeFields: Pick<
  RuntimeConfig,
  "projectionTargets" | "projectionPolicy" | "mounts" | "runtimeBindings"
> = {
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
