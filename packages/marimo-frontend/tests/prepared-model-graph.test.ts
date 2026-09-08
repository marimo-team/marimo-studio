import type { ModelState } from "@marimo-team/frontend/unstable_internal/plugins/impl/anywidget/types";

import { describe, expect, test } from "vite-plus/test";

import type {
  PreparedModelGraphPort,
  PreparedModelGraphSnapshot,
} from "../src/prepared-model-graph.ts";

import {
  PreparedModelGraph,
  PreparedModelGraphReplacementError,
} from "../src/prepared-model-graph.ts";

interface GraphRecord {
  readonly id: string;
  readonly active: boolean;
  readonly revision: string;
  readonly module: string | undefined;
  readonly state: Readonly<ModelState>;
  readonly failValidation?: boolean;
  readonly failPreflight?: boolean;
  readonly failReplay?: boolean;
}

interface LiveModel {
  module: string | undefined;
  state: ModelState;
}

const record = (
  id: string,
  revision: string,
  state: Readonly<ModelState>,
  options: Partial<Omit<GraphRecord, "id" | "revision" | "state">> = {},
): GraphRecord => ({
  id,
  revision,
  state,
  active: true,
  module: "module-a",
  ...options,
});

const graph = (
  records: readonly GraphRecord[],
  files: Readonly<Record<string, string>> = {},
): PreparedModelGraphSnapshot<GraphRecord> => ({
  files,
  records: new Map(records.map((value) => [value.id, value])),
});

const arbitraryAbort = (): AbortSignal => {
  const controller = new AbortController();
  controller.abort({ source: "caller" });
  return controller.signal;
};

class TestGraphPort implements PreparedModelGraphPort<GraphRecord, LiveModel> {
  readonly models = new Map<string, LiveModel>();
  readonly closeFailures = new Set<string>();
  readonly persistentCloseFailures = new Set<string>();
  readonly captureFailures = new Set<string>();
  readonly replayFailures = new Set<string>();
  readonly restoreFailures = new Set<string>();
  files: Readonly<Record<string, string>> = {};

  id(value: GraphRecord): string {
    return value.id;
  }

  active(value: GraphRecord): boolean {
    return value.active;
  }

  same(left: GraphRecord, right: GraphRecord): boolean {
    return left.revision === right.revision;
  }

  changesModule(previous: GraphRecord, next: GraphRecord): boolean {
    return previous.module !== next.module;
  }

  capture(id: string): LiveModel {
    if (this.captureFailures.has(id)) throw new Error(`Capture failed for ${id}`);
    const model = this.models.get(id);
    if (model === undefined) throw new Error(`Missing live model ${id}`);
    return structuredClone(model);
  }

  merge(value: GraphRecord, live: LiveModel): GraphRecord {
    const state = structuredClone(live.state);
    return {
      ...value,
      state,
      revision: `live:${JSON.stringify(state)}`,
    };
  }

  async replay(records: readonly GraphRecord[], signal?: AbortSignal): Promise<void> {
    for (const value of records) {
      signal?.throwIfAborted();
      if (this.replayFailures.delete(value.id) || value.failReplay) {
        throw new Error(`Replay failed for ${value.id}`);
      }
      this.models.set(value.id, {
        module: value.module,
        state: structuredClone(value.state),
      });
    }
  }

  restore(id: string, state: LiveModel): void {
    if (this.restoreFailures.delete(id)) throw new Error(`Restore failed for ${id}`);
    const model = this.models.get(id);
    if (model === undefined) throw new Error(`Missing model ${id} during restore`);
    model.module = state.module;
    model.state = structuredClone(state.state);
  }

  async close(id: string): Promise<void> {
    if (this.persistentCloseFailures.has(id) || this.closeFailures.delete(id)) {
      throw new Error(`Close failed for ${id}`);
    }
    this.models.delete(id);
  }

  setFiles(files: Readonly<Record<string, string>>): void {
    this.files = Object.freeze({ ...files });
  }

  async validate(value: GraphRecord, signal?: AbortSignal): Promise<void> {
    signal?.throwIfAborted();
    if (value.failValidation) throw new Error(`Validation failed for ${value.id}`);
  }

  async preflight(value: GraphRecord, signal?: AbortSignal): Promise<void> {
    signal?.throwIfAborted();
    if (value.failPreflight) throw new Error(`Preflight failed for ${value.id}`);
  }
}

const commit = async (
  runtime: PreparedModelGraph<GraphRecord, LiveModel>,
  next: PreparedModelGraphSnapshot<GraphRecord>,
) => {
  const replacement = await runtime.replace(next);
  await replacement.commit();
  return replacement;
};

describe("prepared Marimo model graph", () => {
  test("rolls back additions, stable updates, and module replacements together", async () => {
    const port = new TestGraphPort();
    const runtime = new PreparedModelGraph(port);
    await commit(
      runtime,
      graph([
        record("stable", "first", { count: 1 }),
        record("replacement", "first", { count: 2 }),
      ]),
    );
    port.models.get("replacement")!.state.count = 9;

    const replacement = await runtime.replace(
      graph([
        record("stable", "next", { count: 3 }),
        record("addition", "next", { count: 4 }),
        record("replacement", "next", { count: 5 }, { module: "module-b" }),
      ]),
    );

    expect(replacement.remount).toBe(true);
    expect(port.models.get("stable")?.state).toEqual({ count: 3 });
    expect(port.models.get("addition")?.state).toEqual({ count: 4 });
    expect(port.models.get("replacement")?.module).toBe("module-b");
    expect(port.models.get("replacement")?.state).toEqual({ count: 9 });
    await replacement.rollback();
    expect(port.models.get("stable")?.state).toEqual({ count: 1 });
    expect(port.models.has("addition")).toBe(false);
    expect(port.models.get("replacement")).toEqual({ module: "module-a", state: { count: 9 } });
    await runtime.dispose();
  });

  test("normalizes pre-aborted no-op and mutating replacements", async () => {
    const port = new TestGraphPort();
    const runtime = new PreparedModelGraph(port);

    await expect(runtime.replace(graph([]), arbitraryAbort())).rejects.toMatchObject({
      name: "AbortError",
    });
    await commit(runtime, graph([record("model-0", "first", { count: 1 })]));
    await expect(
      runtime.replace(graph([record("model-0", "second", { count: 2 })]), arbitraryAbort()),
    ).rejects.toMatchObject({ name: "AbortError" });

    expect(port.models.get("model-0")?.state).toEqual({ count: 1 });
    await runtime.dispose();
  });

  test("checkpoints live browser state and restores it after another generation", async () => {
    const port = new TestGraphPort();
    const runtime = new PreparedModelGraph(port);
    await commit(runtime, graph([record("model-0", "first", { count: 1 })], { first: "one" }));
    port.models.get("model-0")!.state.count = 7;
    const checkpoint = runtime.checkpoint();

    await commit(runtime, graph([record("model-0", "second", { count: 2 })], { second: "two" }));
    expect(port.models.get("model-0")?.state).toEqual({ count: 2 });

    const replacement = await runtime.replace(checkpoint);
    await replacement.commit();

    expect(replacement.mutated).toBe(true);
    expect(replacement.remount).toBe(false);
    expect(port.models.get("model-0")?.state).toEqual({ count: 7 });
    expect(port.files).toEqual({ first: "one" });
    await runtime.dispose();
  });

  test("rolls back a stable update and keeps the captured live state on later commit", async () => {
    const port = new TestGraphPort();
    const runtime = new PreparedModelGraph(port);
    await commit(runtime, graph([record("model-0", "first", { count: 1 })]));
    port.models.get("model-0")!.state.count = 9;

    const replacement = await runtime.replace(graph([record("model-0", "second", { count: 2 })]));
    expect(port.models.get("model-0")?.state).toEqual({ count: 2 });

    await replacement.rollback();

    expect(port.models.get("model-0")?.state).toEqual({ count: 9 });
    await replacement.commit();

    expect(port.models.get("model-0")?.state).toEqual({ count: 9 });
    await runtime.dispose();
  });

  test("restores models removed before a commit failure", async () => {
    const port = new TestGraphPort();
    const runtime = new PreparedModelGraph(port);
    await commit(
      runtime,
      graph([record("model-0", "first", { count: 1 }), record("model-1", "first", { count: 2 })]),
    );
    port.models.get("model-0")!.state.count = 5;
    port.models.get("model-1")!.state.count = 6;
    port.closeFailures.add("model-1");
    const replacement = await runtime.replace(graph([]));

    await expect(replacement.commit()).rejects.toThrow("Close failed for model-1");
    await replacement.rollback();

    expect(port.models.get("model-0")?.state).toEqual({ count: 5 });
    expect(port.models.get("model-1")?.state).toEqual({ count: 6 });
    await runtime.dispose();
  });

  test("preserves partial removal commit and rollback failures", async () => {
    const port = new TestGraphPort();
    const runtime = new PreparedModelGraph(port);
    await commit(
      runtime,
      graph([record("model-0", "first", { count: 1 }), record("model-1", "first", { count: 2 })]),
    );
    port.closeFailures.add("model-1");
    port.replayFailures.add("model-0");
    const replacement = await runtime.replace(graph([]));

    const commitFailure = await replacement.commit().catch((cause) => cause);
    const rollbackFailure = await replacement.rollback().catch((cause) => cause);

    expect(commitFailure).toMatchObject({ message: "Close failed for model-1" });
    expect(rollbackFailure).toBeInstanceOf(PreparedModelGraphReplacementError);
    expect(rollbackFailure).toMatchObject({ remount: true, cause: expect.any(AggregateError) });
    expect(replacementFailure(rollbackFailure).cause).toMatchObject({
      errors: [commitFailure, expect.objectContaining({ message: "Replay failed for model-0" })],
    });
    await expect(runtime.dispose()).rejects.toBe(rollbackFailure);
  });

  test("marks an added-model close failure as requiring remount", async () => {
    const port = new TestGraphPort();
    const runtime = new PreparedModelGraph(port);
    const replacement = await runtime.replace(graph([record("model-0", "first", { count: 1 })]));
    port.closeFailures.add("model-0");

    const failure = await replacement.rollback().catch((cause) => cause);

    expect(failure).toBeInstanceOf(PreparedModelGraphReplacementError);
    expect(failure).toMatchObject({
      remount: true,
      cause: expect.objectContaining({ message: "Close failed for model-0" }),
    });
    await expect(runtime.dispose()).rejects.toBe(failure);
  });

  test("marks a stable-state restore failure as requiring remount", async () => {
    const port = new TestGraphPort();
    const runtime = new PreparedModelGraph(port);
    await commit(runtime, graph([record("model-0", "first", { count: 1 })]));
    const replacement = await runtime.replace(graph([record("model-0", "second", { count: 2 })]));
    port.restoreFailures.add("model-0");

    const failure = await replacement.rollback().catch((cause) => cause);

    expect(failure).toBeInstanceOf(PreparedModelGraphReplacementError);
    expect(failure).toMatchObject({
      remount: true,
      cause: expect.objectContaining({ message: "Restore failed for model-0" }),
    });
    await expect(runtime.dispose()).rejects.toBe(failure);
  });

  test("restores the prior graph when staged replay fails", async () => {
    const port = new TestGraphPort();
    const runtime = new PreparedModelGraph(port);
    await commit(runtime, graph([record("model-0", "first", { count: 1 })]));
    port.models.get("model-0")!.state.count = 4;

    await expect(
      runtime.replace(graph([record("model-0", "second", { count: 2 }, { failReplay: true })])),
    ).rejects.toThrow("Replay failed for model-0");

    expect(port.models.get("model-0")?.state).toEqual({ count: 4 });
    await runtime.dispose();
  });

  test("marks failures after model identity changes as requiring remount", async () => {
    const port = new TestGraphPort();
    const runtime = new PreparedModelGraph(port);
    await commit(runtime, graph([record("model-0", "first", { count: 1 })]));

    await expect(
      runtime.replace(
        graph([
          record(
            "model-0",
            "second",
            { count: 2 },
            {
              module: "module-b",
              failReplay: true,
            },
          ),
        ]),
      ),
    ).rejects.toBeInstanceOf(PreparedModelGraphReplacementError);
    expect(port.models.get("model-0")?.module).toBe("module-a");
    await runtime.dispose();
  });

  test("wraps replacement and rollback failures as requiring remount", async () => {
    const port = new TestGraphPort();
    const runtime = new PreparedModelGraph(port);
    await commit(runtime, graph([record("model-0", "first", { count: 1 })]));
    port.persistentCloseFailures.add("model-0");

    const failure = await runtime
      .replace(graph([record("model-0", "second", { count: 2 }, { module: "module-b" })]))
      .catch((cause) => cause);

    expect(failure).toBeInstanceOf(PreparedModelGraphReplacementError);
    expect(failure).toMatchObject({ remount: true, cause: expect.any(AggregateError) });
    expect(replacementFailure(failure).cause).toMatchObject({
      errors: [expect.any(Error), expect.any(Error)],
    });
    port.persistentCloseFailures.clear();
    await runtime.dispose();
  });

  test("restores files when validation rejects before mutation", async () => {
    const port = new TestGraphPort();
    const runtime = new PreparedModelGraph(port);
    await commit(runtime, graph([record("model-0", "first", {})], { stable: "one" }));

    await expect(
      runtime.replace(
        graph([record("model-1", "next", {}, { failValidation: true })], { staged: "two" }),
      ),
    ).rejects.toThrow("Validation failed for model-1");

    expect(port.files).toEqual({ stable: "one" });
    expect(port.models.has("model-0")).toBe(true);
    await runtime.dispose();
  });

  test("restores files when live-state capture rejects", async () => {
    const port = new TestGraphPort();
    const runtime = new PreparedModelGraph(port);
    await commit(runtime, graph([record("model-0", "first", {})], { stable: "one" }));
    port.captureFailures.add("model-0");

    await expect(
      runtime.replace(graph([record("model-0", "next", { count: 2 })], { staged: "two" })),
    ).rejects.toThrow("Capture failed for model-0");

    expect(port.files).toEqual({ stable: "one" });
    port.captureFailures.clear();
    await runtime.dispose();
  });

  test("disposal rolls back an unsettled replacement and closes the committed graph", async () => {
    const port = new TestGraphPort();
    const runtime = new PreparedModelGraph(port);
    await commit(runtime, graph([record("model-0", "first", { count: 1 })]));
    const replacement = await runtime.replace(graph([record("model-0", "second", { count: 2 })]));

    await runtime.dispose();
    await replacement.rollback();

    expect(port.models.size).toBe(0);
    expect(port.files).toEqual({});
  });
});

function replacementFailure<Value>(value: Value): PreparedModelGraphReplacementError {
  if (!(value instanceof PreparedModelGraphReplacementError)) {
    throw new TypeError("Expected a prepared graph replacement failure.");
  }
  return value;
}
