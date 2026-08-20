import type {
  RuntimeControlBinding,
  RuntimeControls,
} from "@marimo-studio/protocol/runtime-config";

import type {
  ControlEndpoint,
  ControlEvent,
  ControlUpdate,
} from "../src/features/preview/control-types.ts";

export class MemoryEndpoint implements ControlEndpoint {
  readonly values = new Map<string, unknown>();
  readonly applied: (readonly ControlUpdate[])[] = [];
  private readonly listeners = new Set<(update: ControlEvent) => void>();
  private readonly topologyListeners = new Set<(objectId: string) => void>();

  constructor(...updates: readonly ControlUpdate[]) {
    updates.forEach((update) => this.values.set(update.objectId, update.value));
  }

  snapshot(): readonly ControlUpdate[] {
    return Array.from(this.values, ([objectId, value]) => ({ objectId, value }));
  }

  subscribe(listener: (update: ControlEvent) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  subscribeTopology(listener: (objectId: string) => void): () => void {
    this.topologyListeners.add(listener);
    return () => this.topologyListeners.delete(listener);
  }

  async apply(updates: readonly ControlUpdate[]): Promise<void> {
    this.applied.push(updates);
    updates.forEach((update) => this.values.set(update.objectId, update.value));
  }

  emit(update: ControlUpdate): void {
    this.values.set(update.objectId, update.value);
    this.listeners.forEach((listener) => listener({ ...update, origin: "input" }));
  }

  register(update: ControlUpdate): void {
    this.values.set(update.objectId, update.value);
    this.topology(update.objectId);
    this.listeners.forEach((listener) => listener({ ...update, origin: "registration" }));
  }

  topology(objectId: string): void {
    this.topologyListeners.forEach((listener) => listener(objectId));
  }

  dispose(): void {
    this.listeners.clear();
    this.topologyListeners.clear();
  }
}

export class DeferredApplyEndpoint extends MemoryEndpoint {
  private readonly pending: Array<{
    reject: (error: Error) => void;
    resolve: () => void;
    updates: readonly ControlUpdate[];
  }> = [];

  override apply(updates: readonly ControlUpdate[]): Promise<void> {
    this.applied.push(updates);
    return new Promise((resolve, reject) => {
      this.pending.push({ reject, resolve, updates });
    });
  }

  rejectNext(error: Error): void {
    this.pending.shift()?.reject(error);
  }

  resolveNext(): void {
    const pending = this.pending.shift();
    pending?.updates.forEach((update) => this.values.set(update.objectId, update.value));
    pending?.resolve();
  }
}

export class TransientPeerEndpoint extends MemoryEndpoint {
  readonly kernelValues = new Map<string, unknown>();
  private failNextSend = true;

  constructor(...updates: readonly ControlUpdate[]) {
    super(...updates);
    updates.forEach((update) => this.kernelValues.set(update.objectId, update.value));
  }

  override async apply(updates: readonly ControlUpdate[]): Promise<void> {
    this.applied.push(updates);
    const previous = updates.map(({ objectId }) => ({
      objectId,
      value: this.values.get(objectId),
    }));
    updates.forEach((update) => this.values.set(update.objectId, update.value));
    if (this.failNextSend) {
      this.failNextSend = false;
      previous.forEach((update) => this.values.set(update.objectId, update.value));
      throw new Error("peer send failed");
    }
    updates.forEach((update) => this.kernelValues.set(update.objectId, update.value));
  }
}

export class SelfBindingEndpoint extends MemoryEndpoint {
  constructor(
    private readonly bindings: NonNullable<RuntimeControls["bindings"]>,
    ...updates: readonly ControlUpdate[]
  ) {
    super(...updates);
  }

  controlBindings(): NonNullable<RuntimeControls["bindings"]> {
    return this.bindings;
  }
}

export class MutableBindingEndpoint extends MemoryEndpoint {
  constructor(
    private bindings: NonNullable<RuntimeControls["bindings"]> | undefined,
    ...updates: readonly ControlUpdate[]
  ) {
    super(...updates);
  }

  controlBindings(): NonNullable<RuntimeControls["bindings"]> | undefined {
    return this.bindings;
  }

  setBindings(bindings: NonNullable<RuntimeControls["bindings"]>): void {
    this.bindings = bindings;
  }
}

export class RejectOnceBindingEndpoint extends MutableBindingEndpoint {
  private failure: Error | undefined;

  failNext(error: Error): void {
    this.failure = error;
  }

  override async apply(updates: readonly ControlUpdate[]): Promise<void> {
    this.applied.push(updates);
    const failure = this.failure;
    this.failure = undefined;
    if (failure !== undefined) {
      throw failure;
    }
    updates.forEach((update) => this.values.set(update.objectId, update.value));
  }
}

export class LocalApplyEndpoint extends SelfBindingEndpoint {
  readonly localApplied: (readonly ControlUpdate[])[] = [];

  async applyLocal(updates: readonly ControlUpdate[]): Promise<void> {
    this.localApplied.push(updates);
  }
}

export const rootBinding = (input: string): RuntimeControlBinding => ({ input, path: [] });

export const keyBinding = (input: string, key: string): RuntimeControlBinding => ({
  input,
  path: [{ kind: "key", value: key }],
});

export const controls = (
  bindings: Readonly<Record<string, RuntimeControlBinding>>,
): RuntimeControls => ({ bindings: { ...bindings } });
