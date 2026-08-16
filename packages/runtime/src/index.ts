import type { RuntimeConfig } from "@marimo-studio/protocol/runtime-config";

export interface RuntimeContext {
  readonly presentation: RuntimeConfig;
  readonly root: HTMLElement;
}

export interface RuntimeSession {
  readonly id: string;
  readonly sessionId?: string;
  update(config: RuntimeConfig): "applied" | "reload";
  updateQuery(query: string): Promise<void>;
  dispose(): void;
}

export type RuntimeData = Readonly<RuntimeConfig["runtime"]["data"]>;

export interface PresentationRuntime {
  readonly id: string;
  mount(context: RuntimeContext, data: RuntimeData): Promise<RuntimeSession>;
}

export interface RuntimeRegistry {
  readonly runtimes: readonly PresentationRuntime[];
  get(id: string): PresentationRuntime;
  has(id: string): boolean;
}

export const definePresentationRuntime = (runtime: PresentationRuntime): PresentationRuntime =>
  Object.freeze(runtime);

export const createRuntimeRegistry = (
  definitions: readonly PresentationRuntime[],
): RuntimeRegistry => {
  const runtimes = definitions.map(definePresentationRuntime);
  const byId = new Map<string, PresentationRuntime>();
  for (const runtime of runtimes) {
    if (!/^[a-z][a-z0-9-]*$/.test(runtime.id)) {
      throw new Error(`Invalid runtime ID ${JSON.stringify(runtime.id)}`);
    }
    if (byId.has(runtime.id)) {
      throw new Error(`Duplicate runtime ID ${JSON.stringify(runtime.id)}`);
    }
    byId.set(runtime.id, runtime);
  }
  const frozen = Object.freeze(runtimes);
  return Object.freeze({
    runtimes: frozen,
    get(id: string): PresentationRuntime {
      const runtime = byId.get(id);
      if (!runtime) {
        throw new Error(`Unknown runtime ${JSON.stringify(id)}`);
      }
      return runtime;
    },
    has: (id: string): boolean => byId.has(id),
  });
};
