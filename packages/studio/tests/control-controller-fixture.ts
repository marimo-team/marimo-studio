import type {
  RuntimeControlBinding,
  RuntimeControls,
} from "@marimo-studio/protocol/runtime-config";

import { vi } from "vite-plus/test";

import type {
  fetchRuntimeControls,
  RuntimeControlSnapshot,
} from "../src/features/preview/control-remote.ts";
import type {
  ControlEndpoint,
  ControlEvent,
  ControlFrameConnector,
  ControlUpdate,
} from "../src/features/preview/control-types.ts";

import { PreviewControlController } from "../src/features/preview/control-controller.ts";
import { wasmRuntime } from "./runtime-fixtures.ts";

export const endpoint = (bindings?: RuntimeControls): ControlEndpoint => ({
  snapshot: () => [],
  controlBindings: bindings?.bindings === undefined ? undefined : () => bindings.bindings,
  subscribe: () => () => {},
  apply: vi.fn(async () => {}),
  dispose: vi.fn(),
});

export class TopologyEndpoint implements ControlEndpoint {
  readonly applied: (readonly ControlUpdate[])[] = [];
  private readonly listeners = new Set<(update: ControlEvent) => void>();
  private readonly topologyListeners = new Set<(objectId: string) => void>();
  private readonly bindingListeners = new Set<
    (bindings: NonNullable<RuntimeControls["bindings"]>) => void
  >();

  constructor(
    private bindings: NonNullable<RuntimeControls["bindings"]>,
    private readonly values: Map<string, unknown>,
    private readonly selfAuthored = true,
  ) {}

  snapshot(): readonly ControlUpdate[] {
    return Array.from(this.values, ([objectId, value]) => ({ objectId, value }));
  }

  controlBindings(): NonNullable<RuntimeControls["bindings"]> | undefined {
    return this.selfAuthored ? this.bindings : undefined;
  }

  subscribe(listener: (update: ControlEvent) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  subscribeTopology(listener: (objectId: string) => void): () => void {
    this.topologyListeners.add(listener);
    return () => this.topologyListeners.delete(listener);
  }

  subscribeControlBindings(
    listener: (bindings: NonNullable<RuntimeControls["bindings"]>) => void,
  ): () => void {
    this.bindingListeners.add(listener);
    return () => this.bindingListeners.delete(listener);
  }

  async apply(updates: readonly ControlUpdate[]): Promise<void> {
    this.applied.push(updates);
  }

  register(update: ControlUpdate): void {
    this.values.set(update.objectId, update.value);
    this.topologyListeners.forEach((listener) => listener(update.objectId));
    this.listeners.forEach((listener) => listener({ ...update, origin: "registration" }));
  }

  emit(update: ControlUpdate): void {
    this.values.set(update.objectId, update.value);
    this.listeners.forEach((listener) => listener({ ...update, origin: "input" }));
  }

  publishBindings(bindings: NonNullable<RuntimeControls["bindings"]>): void {
    this.bindings = bindings;
    this.bindingListeners.forEach((listener) => listener(bindings));
  }

  subscriberCount(): number {
    return this.listeners.size;
  }

  dispose(): void {
    this.listeners.clear();
    this.topologyListeners.clear();
    this.bindingListeners.clear();
  }
}

export const changed = (
  snapshot: Omit<RuntimeControlSnapshot, "controlRevision">,
  controlRevision = 1,
) => ({
  kind: "changed" as const,
  snapshot: { ...snapshot, controlRevision },
  etag: `"etag-${controlRevision}"`,
});

interface ControlControllerFixtureOptions {
  readonly connect?: ControlFrameConnector;
  readonly fetchControls: typeof fetchRuntimeControls;
  readonly onContextUnavailable?: () => void;
}

export const createControlController = ({
  connect,
  fetchControls,
  onContextUnavailable,
}: ControlControllerFixtureOptions) => {
  const editor = document.createElement("iframe");
  const preview = document.createElement("iframe");
  preview.src = "/preview?marimo_studio_client=browser-client-1234";
  const controller = new PreviewControlController({
    runtime: wasmRuntime,
    peerRuntime: "editor",
    editor,
    preview,
    supportUrl: () => "/_marimo-studio/views/dashboard",
    connect,
    fetchControls,
    onContextUnavailable,
  });
  return { controller, editor, preview };
};

export type { RuntimeControlBinding };
