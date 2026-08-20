import {
  jsonObjectSchema,
  jsonValueSchema,
  type JsonValue,
} from "@marimo-studio/protocol/runtime-config";

import type { ControlEndpoint, ControlEvent, ControlUpdate } from "./control-types.ts";

interface JsonControlUpdate {
  readonly objectId: string;
  readonly value: JsonValue;
  readonly committed: boolean;
}

interface KnownControlValue {
  readonly value: JsonValue;
  readonly committed: boolean;
}

interface ControlDrain {
  readonly promise: Promise<void>;
  settle(error?: Error): void;
}

const settledControlWrite = Promise.resolve();

const sameJsonValue = (left: JsonValue, right: JsonValue): boolean => {
  if (left === right) {
    return true;
  }
  if (Array.isArray(left) || Array.isArray(right)) {
    return (
      Array.isArray(left) &&
      Array.isArray(right) &&
      left.length === right.length &&
      left.every((value, index) => sameJsonValue(value, right[index]!))
    );
  }
  const leftObject = jsonObjectSchema.safeParse(left);
  const rightObject = jsonObjectSchema.safeParse(right);
  if (!leftObject.success || !rightObject.success) {
    return false;
  }
  const keys = Object.keys(leftObject.data);
  return (
    keys.length === Object.keys(rightObject.data).length &&
    keys.every(
      (key) =>
        Object.hasOwn(rightObject.data, key) &&
        sameJsonValue(leftObject.data[key]!, rightObject.data[key]!),
    )
  );
};

const controlWriteError = (cause: unknown): Error =>
  cause instanceof Error ? cause : new Error(String(cause));

const createControlDrain = (): ControlDrain => {
  let settled = false;
  let resolvePromise = () => {};
  let rejectPromise = (_error: Error) => {};
  const promise = new Promise<void>((resolve, reject) => {
    resolvePromise = resolve;
    rejectPromise = reject;
  });
  return {
    promise,
    settle(error) {
      if (settled) {
        return;
      }
      settled = true;
      if (error === undefined) {
        resolvePromise();
      } else {
        rejectPromise(error);
      }
    },
  };
};

export class ControlWriter {
  private readonly desired = new Map<string, JsonControlUpdate>();
  private readonly inflight = new Map<string, JsonControlUpdate>();
  private readonly values = new Map<string, KnownControlValue>();
  private drain: ControlDrain | undefined;
  private disposed = false;

  constructor(private readonly endpoint: ControlEndpoint) {
    endpoint.snapshot().forEach((update) => {
      const value = jsonValueSchema.safeParse(update.value);
      if (value.success) {
        this.values.set(update.objectId, { value: value.data, committed: true });
      }
    });
  }

  observe(update: ControlEvent): boolean {
    if (this.disposed) {
      return false;
    }
    const value = jsonValueSchema.safeParse(update.value);
    if (!value.success) {
      return false;
    }
    const inflight = this.inflight.get(update.objectId);
    const desired = this.desired.get(update.objectId);
    if (update.origin === "registration") {
      if (inflight !== undefined) {
        if (
          !sameJsonValue(inflight.value, value.data) &&
          this.desired.get(update.objectId) === inflight
        ) {
          this.desired.set(update.objectId, { ...inflight });
        }
        return false;
      }
      if (desired !== undefined) {
        return false;
      }
      this.values.set(update.objectId, { value: value.data, committed: true });
      return true;
    }
    this.values.set(update.objectId, { value: value.data, committed: true });
    if (inflight === undefined || sameJsonValue(inflight.value, value.data)) {
      this.desired.delete(update.objectId);
    } else {
      this.desired.set(update.objectId, {
        objectId: update.objectId,
        value: value.data,
        committed: true,
      });
    }
    return true;
  }

  write(updates: readonly ControlUpdate[], committed = true): Promise<void> {
    if (this.disposed) {
      return settledControlWrite;
    }
    if (updates.length === 0) {
      return this.drain?.promise ?? settledControlWrite;
    }
    const changed: JsonControlUpdate[] = [];
    updates.forEach((update) => {
      const value = jsonValueSchema.safeParse(update.value);
      if (!value.success) {
        return;
      }
      const desired = this.desired.get(update.objectId);
      const current = desired ?? this.values.get(update.objectId);
      if (
        (desired !== undefined || this.values.has(update.objectId)) &&
        current !== undefined &&
        sameJsonValue(current.value, value.data) &&
        (!committed || current.committed)
      ) {
        return;
      }
      changed.push({
        objectId: update.objectId,
        value: value.data,
        committed,
      });
    });
    if (changed.length === 0) {
      return this.drain?.promise ?? settledControlWrite;
    }
    changed.forEach((update) => this.desired.set(update.objectId, update));
    if (this.drain !== undefined) {
      return this.drain.promise;
    }
    const drain = createControlDrain();
    this.drain = drain;
    void this.runDrain(drain);
    return drain.promise;
  }

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    this.desired.clear();
    this.inflight.clear();
    const drain = this.drain;
    this.drain = undefined;
    drain?.settle();
  }

  private async runDrain(owner: ControlDrain): Promise<void> {
    let firstError: Error | undefined;
    try {
      while (!this.disposed && this.desired.size > 0) {
        const updates = Array.from(this.desired.values());
        updates.forEach((update) => this.inflight.set(update.objectId, update));
        const committed = updates.some((update) => update.committed);
        const apply =
          committed || this.endpoint.applyLocal === undefined
            ? this.endpoint.apply.bind(this.endpoint)
            : this.endpoint.applyLocal.bind(this.endpoint);
        try {
          await apply(updates.map(({ objectId, value }) => ({ objectId, value })));
        } catch (cause) {
          updates.forEach((update) => {
            this.inflight.delete(update.objectId);
            if (this.desired.get(update.objectId) === update) {
              this.desired.delete(update.objectId);
            }
          });
          firstError ??= controlWriteError(cause);
          continue;
        }
        updates.forEach((update) => {
          this.inflight.delete(update.objectId);
          this.values.set(update.objectId, {
            value: update.value,
            committed: committed || this.endpoint.applyLocal === undefined,
          });
          if (this.desired.get(update.objectId) === update) {
            this.desired.delete(update.objectId);
          }
        });
      }
    } catch (cause) {
      firstError ??= controlWriteError(cause);
    } finally {
      if (this.drain === owner) {
        this.drain = undefined;
        owner.settle(firstError);
      }
    }
  }
}
