import type { RuntimeConfig } from "@marimo-studio/protocol/runtime-config";
import type { RuntimeDescriptor } from "@marimo-studio/protocol/runtime-descriptor";

import { runtimeDescriptorSchema } from "@marimo-studio/protocol/runtime-descriptor";

export interface RuntimeContext {
  readonly presentation: RuntimeConfig;
  readonly root: HTMLElement;
  readonly signal: AbortSignal;
  commitRuntimeInstance(instance: string): void;
}

export interface RuntimeSession {
  readonly id: string;
  readonly initialQueryApplied?: boolean;
  readonly sessionId?: string;
  updateQuery?(query: string, signal: AbortSignal): Promise<void>;
  beginRevision(signal: AbortSignal): Promise<RuntimeSessionRevision>;
  dispose(): void | Promise<void>;
}

export interface RuntimeSessionRevision {
  apply(config: RuntimeConfig): Promise<"applied" | "reload">;
  commit(): void | Promise<void>;
  rollback(): void | Promise<void>;
}

export type RuntimeData = Readonly<RuntimeConfig["runtime"]["data"]>;

export interface PresentationRuntime {
  readonly descriptor: RuntimeDescriptor;
  mount(context: RuntimeContext, data: RuntimeData): Promise<RuntimeSession>;
}

export interface RuntimeRegistry {
  readonly runtimes: readonly PresentationRuntime[];
  resolve(descriptor: RuntimeDescriptor): PresentationRuntime;
  has(id: string): boolean;
}

const sameDescriptor = (left: RuntimeDescriptor, right: RuntimeDescriptor): boolean =>
  left.id === right.id &&
  left.label === right.label &&
  left.description === right.description &&
  left.execution === right.execution &&
  left.projections.cell === right.projections.cell &&
  left.projections.output === right.projections.output &&
  left.projections.value === right.projections.value &&
  left.controls === right.controls &&
  left.query === right.query &&
  left.preparation === right.preparation &&
  left.session === right.session;

export const definePresentationRuntime = (runtime: PresentationRuntime): PresentationRuntime => {
  const parsed = runtimeDescriptorSchema.parse(runtime.descriptor);
  const descriptor = Object.freeze({
    ...parsed,
    projections: Object.freeze(parsed.projections),
  });
  return Object.freeze({ ...runtime, descriptor: Object.freeze(descriptor) });
};

export const createRuntimeRegistry = (
  definitions: readonly PresentationRuntime[],
): RuntimeRegistry => {
  const runtimes = definitions.map(definePresentationRuntime);
  const byId = new Map<string, PresentationRuntime>();
  for (const runtime of runtimes) {
    const { id } = runtime.descriptor;
    if (byId.has(id)) {
      throw new Error(`Duplicate runtime ID ${JSON.stringify(id)}`);
    }
    byId.set(id, runtime);
  }
  const frozen = Object.freeze(runtimes);
  return Object.freeze({
    runtimes: frozen,
    resolve(descriptor: RuntimeDescriptor): PresentationRuntime {
      const runtime = byId.get(descriptor.id);
      if (!runtime) {
        throw new Error(`Unknown runtime ${JSON.stringify(descriptor.id)}`);
      }
      if (!sameDescriptor(runtime.descriptor, descriptor)) {
        throw new Error(
          `Runtime descriptor ${JSON.stringify(descriptor.id)} does not match the registered runtime`,
        );
      }
      return runtime;
    },
    has: (id: string): boolean => byId.has(id),
  });
};
