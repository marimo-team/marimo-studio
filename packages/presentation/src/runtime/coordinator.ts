import type { RuntimeConfig } from "@marimo-studio/protocol/runtime-config";
import type { RuntimeRegistry, RuntimeSession } from "@marimo-studio/runtime";

let session: RuntimeSession | undefined;
let mountGeneration = 0;

export type RuntimeUpdate = "applied" | "pending" | "reload";

export class RuntimeMountCancelledError extends Error {
  constructor() {
    super("Runtime mount was cancelled");
    this.name = "RuntimeMountCancelledError";
  }
}

export const mountConfiguredRuntime = async (
  registry: RuntimeRegistry,
  config: RuntimeConfig,
  root: HTMLElement,
): Promise<RuntimeSession> => {
  const generation = ++mountGeneration;
  const runtime = registry.get(config.runtime.id);
  const mounted = await runtime.mount({ presentation: config, root }, config.runtime.data);
  if (generation !== mountGeneration) {
    mounted.dispose();
    throw new RuntimeMountCancelledError();
  }
  session = mounted;
  return mounted;
};

export const updateConfiguredRuntime = (config: RuntimeConfig): RuntimeUpdate => {
  return session?.update(config) ?? "pending";
};

export const updateConfiguredRuntimeQuery = async (query: string): Promise<void> => {
  if (!session) {
    throw new Error("The presentation runtime is still starting");
  }
  await session.updateQuery(query);
};

export const disposeConfiguredRuntime = (): void => {
  mountGeneration += 1;
  session?.dispose();
  session = undefined;
};
