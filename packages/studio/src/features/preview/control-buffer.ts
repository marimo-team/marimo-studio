import type { JsonValue } from "@marimo-studio/protocol/runtime-config";

import type { ControlEvent, ControlSource, EndpointControlBinding } from "./control-types.ts";

export const MAX_BUFFERED_CONTROLS = 256;
export const MAX_BUFFERED_CONTROL_BYTES = 16 * 1024 * 1024;
const bufferEncoder = new TextEncoder();

export interface BufferedControlUpdate {
  readonly binding?: EndpointControlBinding;
  readonly bytes: number;
  readonly source: ControlSource;
  readonly update: ControlEvent;
}

const preservesSemanticIntent = (
  update: ControlEvent,
  binding: EndpointControlBinding | undefined,
): boolean => update.origin === "input" && binding !== undefined;

export const controlUpdateBytes = (
  objectId: string,
  value: JsonValue,
  binding?: EndpointControlBinding,
): number => bufferEncoder.encode(JSON.stringify([objectId, value, binding ?? null])).byteLength;

export class QuarantinedControlBuffer {
  private readonly updates = new Map<string, BufferedControlUpdate>();
  private readonly snapshots = new Set<ControlSource>();
  private readonly snapshotOnly = new Set<ControlSource>();
  private bytes = 0;

  add(
    source: ControlSource,
    update: ControlEvent,
    value: JsonValue,
    binding?: EndpointControlBinding,
  ): void {
    if (
      this.snapshotOnly.has(source) ||
      (this.snapshots.has(source) && !preservesSemanticIntent(update, binding))
    ) {
      return;
    }
    const key = JSON.stringify([source, update.objectId]);
    const capturedBinding =
      binding === undefined
        ? undefined
        : { input: binding.input, path: structuredClone(binding.path) };
    const core = {
      bytes: controlUpdateBytes(key, value, capturedBinding),
      source,
      update: { objectId: update.objectId, value: structuredClone(value), origin: update.origin },
    };
    const buffered: BufferedControlUpdate =
      capturedBinding === undefined ? core : { ...core, binding: capturedBinding };
    const previous = this.updates.get(key);
    if (previous?.update.origin === "input" && update.origin === "registration") {
      return;
    }
    if (previous !== undefined) {
      this.bytes -= previous.bytes;
      this.updates.delete(key);
    }
    this.store(key, buffered);
  }

  retain(buffered: BufferedControlUpdate): void {
    if (
      this.snapshotOnly.has(buffered.source) ||
      (this.snapshots.has(buffered.source) &&
        !preservesSemanticIntent(buffered.update, buffered.binding))
    ) {
      return;
    }
    const key = JSON.stringify([buffered.source, buffered.update.objectId]);
    const previous = this.updates.get(key);
    if (previous !== undefined) {
      if (previous.update.origin !== "registration" || buffered.update.origin !== "input") {
        return;
      }
      this.bytes -= previous.bytes;
      this.updates.delete(key);
    }
    this.store(key, buffered);
  }

  updateCount(): number {
    return this.updates.size;
  }

  private store(key: string, buffered: BufferedControlUpdate): void {
    this.updates.set(key, buffered);
    this.bytes += buffered.bytes;
    while (this.updates.size > MAX_BUFFERED_CONTROLS || this.bytes > MAX_BUFFERED_CONTROL_BYTES) {
      const oldest = this.updates.values().next().value;
      if (oldest === undefined) {
        break;
      }
      this.snapshots.add(oldest.source);
      this.snapshotOnly.add(oldest.source);
      this.removeSource(oldest.source);
    }
  }

  clear(): void {
    this.updates.clear();
    this.snapshots.clear();
    this.snapshotOnly.clear();
    this.bytes = 0;
  }

  hasWork(): boolean {
    return this.snapshots.size > 0 || this.updates.size > 0;
  }

  hasSnapshots(): boolean {
    return this.snapshots.size > 0;
  }

  snapshotSources(): readonly ControlSource[] {
    return Array.from(this.snapshots);
  }

  snapshotCaptured(source: ControlSource): void {
    this.snapshots.delete(source);
    this.snapshotOnly.delete(source);
  }

  requireSnapshot(source: ControlSource, preserveUpdates = false): void {
    this.snapshots.add(source);
    if (!preserveUpdates) {
      this.snapshotOnly.add(source);
      this.removeSource(source);
      return;
    }
    this.updates.forEach((entry, key) => {
      if (entry.source === source && !preservesSemanticIntent(entry.update, entry.binding)) {
        this.updates.delete(key);
        this.bytes -= entry.bytes;
      }
    });
  }

  takeOldest(): BufferedControlUpdate | undefined {
    const oldest = this.updates.entries().next().value;
    if (oldest === undefined) {
      return undefined;
    }
    const [key, update] = oldest;
    this.updates.delete(key);
    this.bytes -= update.bytes;
    return update;
  }

  private removeSource(source: ControlSource): void {
    this.updates.forEach((entry, key) => {
      if (entry.source === source) {
        this.updates.delete(key);
        this.bytes -= entry.bytes;
      }
    });
  }
}
