import { describe, expect, it, vi } from "vite-plus/test";

import {
  type ControlEndpoint,
  type ControlUpdate,
  type RuntimeCellMap,
  synchronizeControlEndpoints,
} from "../src/features/preview/control-sync";

class MemoryEndpoint implements ControlEndpoint {
  readonly values = new Map<string, unknown>();
  readonly applied: (readonly ControlUpdate[])[] = [];
  private readonly listeners = new Set<(update: ControlUpdate) => void>();

  constructor(...updates: readonly ControlUpdate[]) {
    updates.forEach((update) => this.values.set(update.objectId, update.value));
  }

  snapshot(): readonly ControlUpdate[] {
    return Array.from(this.values, ([objectId, value]) => ({ objectId, value }));
  }

  subscribe(listener: (update: ControlUpdate) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  async apply(updates: readonly ControlUpdate[]): Promise<void> {
    this.applied.push(updates);
    updates.forEach((update) => this.values.set(update.objectId, update.value));
  }

  emit(update: ControlUpdate): void {
    this.values.set(update.objectId, update.value);
    this.listeners.forEach((listener) => listener(update));
  }

  dispose(): void {
    this.listeners.clear();
  }
}

class DeferredApplyEndpoint extends MemoryEndpoint {
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

  rejectNext(error = new Error("control write failed")): void {
    this.pending.shift()?.reject(error);
  }

  resolveNext(): void {
    const pending = this.pending.shift();
    pending?.updates.forEach((update) => this.values.set(update.objectId, update.value));
    pending?.resolve();
  }
}

class RecoveringEndpoint extends MemoryEndpoint {
  failures = 0;

  override async apply(updates: readonly ControlUpdate[]): Promise<void> {
    if (this.failures > 0) {
      this.failures -= 1;
      this.applied.push(updates);
      throw new Error("control write failed");
    }
    await super.apply(updates);
  }
}

describe("control state synchronization", () => {
  it("keeps editor initialization authoritative over registration changes", async () => {
    const binding = { input: "scale", path: [] };
    const editor = new MemoryEndpoint({ objectId: "live-control", value: 3 });
    const preview = new MemoryEndpoint({ objectId: "prepared-control", value: 2 });
    const controls = { cells: {}, bindings: { "prepared-control": binding } };
    const sync = await synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: { cells: {}, bindings: { "live-control": binding } },
      previewControls: controls,
      previewBaseline: {
        metadata: controls,
        values: [{ objectId: "prepared-control", value: 1 }],
        touched: new Set(),
      },
    });
    expect(preview.snapshot()).toEqual([{ objectId: "prepared-control", value: 3 }]);
    expect(editor.snapshot()).toEqual([{ objectId: "live-control", value: 3 }]);
    sync.dispose();
  });

  it("preserves a local selection made while editor metadata loads and remaps new aliases", async () => {
    const binding = { input: "sport", path: [] };
    const before = "PKri-projection-before-ui-sport";
    const current = "PKri-projection-current-ui-sport";
    let metadata: RuntimeCellMap = { cells: {}, bindings: { [current]: binding } };
    const editor = new MemoryEndpoint({ objectId: "live-PKri-0", value: ["All sports"] });
    const preview = Object.assign(new MemoryEndpoint({ objectId: current, value: ["aquatics"] }), {
      metadata: () => metadata,
    });
    const sync = await synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: { cells: {}, bindings: { "live-PKri-0": binding } },
      previewControls: metadata,
      previewBaseline: {
        metadata: { cells: {}, bindings: { [before]: binding } },
        values: [{ objectId: before, value: ["All sports"] }],
        touched: new Set([before]),
      },
    });
    expect(preview.snapshot()).toEqual([{ objectId: current, value: ["aquatics"] }]);
    expect(editor.snapshot()).toEqual([{ objectId: "live-PKri-0", value: ["aquatics"] }]);

    const next = "PKri-projection-next-ui-sport";
    metadata = { cells: {}, bindings: { [next]: binding } };
    preview.values.clear();
    preview.emit({ objectId: next, value: ["archery"], origin: "registration" });
    await Promise.resolve();
    expect(editor.snapshot()).toEqual([{ objectId: "live-PKri-0", value: ["aquatics"] }]);
    editor.emit({ objectId: "live-PKri-0", value: ["boxing"] });
    await vi.waitFor(() =>
      expect(preview.snapshot()).toEqual([{ objectId: next, value: ["boxing"] }]),
    );
    preview.emit({ objectId: next, value: ["archery"], origin: "input" });
    await vi.waitFor(() =>
      expect(editor.snapshot()).toEqual([{ objectId: "live-PKri-0", value: ["archery"] }]),
    );
    sync.dispose();
  });

  it("matches prepared aliases to native controls by input and path", async () => {
    const first = "PKri-projection-first-ui-sport";
    const second = "PKri-projection-second-ui-sport";
    const editor = new MemoryEndpoint({ objectId: "live-PKri-0", value: ["aquatics"] });
    const preview = new MemoryEndpoint(
      { objectId: first, value: ["All sports"] },
      { objectId: second, value: ["All sports"] },
    );
    const binding = { input: "filters", path: [{ kind: "key" as const, value: "sport" }] };
    const sync = await synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: { cells: { controls: "live-PKri" }, bindings: { "live-PKri-0": binding } },
      previewControls: {
        cells: { controls: "PKri" },
        bindings: { [first]: binding, [second]: binding },
      },
    });

    expect(preview.snapshot()).toEqual([
      { objectId: first, value: ["aquatics"] },
      { objectId: second, value: ["aquatics"] },
    ]);
    preview.emit({ objectId: second, value: ["archery"] });
    await vi.waitFor(() =>
      expect(editor.snapshot()).toEqual([{ objectId: "live-PKri-0", value: ["archery"] }]),
    );
    sync.dispose();
  });

  it("translates stable cell identities between independent runtimes", async () => {
    const editor = new MemoryEndpoint({ objectId: "live-control-0", value: ["Growth"] });
    const preview = new MemoryEndpoint({
      objectId: "wasm-shifted-control-0",
      value: ["Base"],
    });
    const sync = await synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: { cells: { controls: "live-control" } },
      previewControls: { cells: { controls: "wasm-shifted-control" } },
    });

    expect(preview.values.get("wasm-shifted-control-0")).toEqual(["Growth"]);

    editor.emit({ objectId: "live-control-0", value: ["Stretch"] });
    await Promise.resolve();
    expect(preview.values.get("wasm-shifted-control-0")).toEqual(["Stretch"]);

    preview.emit({ objectId: "wasm-shifted-control-0", value: ["Base"] });
    await Promise.resolve();
    expect(editor.values.get("live-control-0")).toEqual(["Base"]);
    sync.dispose();
  });

  it("leaves unmatched and non-JSON control values local", async () => {
    const editor = new MemoryEndpoint(
      { objectId: "live-known-0", value: 2 },
      { objectId: "live-private-0", value: 3 },
    );
    const preview = new MemoryEndpoint({ objectId: "wasm-known-0", value: 1 });
    const sync = await synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: {
        cells: { known: "live-known", private: "live-private" },
      },
      previewControls: { cells: { known: "wasm-known" } },
    });

    expect(preview.applied).toEqual([[{ objectId: "wasm-known-0", value: 2 }]]);
    editor.emit({ objectId: "live-known-0", value: undefined });
    expect(preview.applied).toHaveLength(1);
    sync.dispose();
  });

  it("skips controls that already match during initial synchronization", async () => {
    const editor = new MemoryEndpoint(
      { objectId: "live-controls-0", value: 1 },
      { objectId: "live-controls-1", value: 2 },
    );
    const preview = new MemoryEndpoint(
      { objectId: "wasm-controls-0", value: 1 },
      { objectId: "wasm-controls-1", value: 0 },
    );

    const sync = await synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: { cells: { controls: "live-controls" } },
      previewControls: { cells: { controls: "wasm-controls" } },
    });

    expect(preview.applied).toEqual([[{ objectId: "wasm-controls-1", value: 2 }]]);
    sync.dispose();
  });

  it("serializes initial and live editor writes and keeps the latest value", async () => {
    const editor = new MemoryEndpoint({ objectId: "live-control-0", value: "Initial" });
    const preview = new DeferredApplyEndpoint({
      objectId: "wasm-control-0",
      value: "Preview",
    });
    const synchronizing = synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: { cells: { controls: "live-control" } },
      previewControls: { cells: { controls: "wasm-control" } },
    });
    await Promise.resolve();

    editor.emit({ objectId: "live-control-0", value: "Intermediate" });
    editor.emit({ objectId: "live-control-0", value: "Latest" });
    expect(preview.applied).toEqual([[{ objectId: "wasm-control-0", value: "Initial" }]]);

    preview.resolveNext();
    await vi.waitFor(() => expect(preview.applied).toHaveLength(2));
    expect(preview.applied[1]).toEqual([{ objectId: "wasm-control-0", value: "Latest" }]);
    preview.resolveNext();
    const sync = await synchronizing;
    sync.dispose();
  });

  it("serializes preview writes before applying them to the editor", async () => {
    const editor = new DeferredApplyEndpoint({
      objectId: "live-control-0",
      value: "Initial",
    });
    const preview = new MemoryEndpoint({ objectId: "wasm-control-0", value: "Preview" });
    const sync = await synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: { cells: { controls: "live-control" } },
      previewControls: { cells: { controls: "wasm-control" } },
    });

    preview.emit({ objectId: "wasm-control-0", value: "Intermediate" });
    preview.emit({ objectId: "wasm-control-0", value: "Latest" });
    expect(editor.applied).toEqual([[{ objectId: "live-control-0", value: "Intermediate" }]]);

    editor.resolveNext();
    await vi.waitFor(() => expect(editor.applied).toHaveLength(2));
    expect(editor.applied[1]).toEqual([{ objectId: "live-control-0", value: "Latest" }]);
    editor.resolveNext();
    sync.dispose();
  });

  it("retains a failed write and recovers with the newest control value", async () => {
    const editor = new MemoryEndpoint({ objectId: "live-control-0", value: "Initial" });
    const preview = new RecoveringEndpoint({ objectId: "wasm-control-0", value: "Preview" });
    const statuses: string[] = [];
    const sync = await synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: { cells: { controls: "live-control" } },
      previewControls: { cells: { controls: "wasm-control" } },
      onStatus: (status) => statuses.push(status.phase),
    });
    preview.failures = 1;

    editor.emit({ objectId: "live-control-0", value: "Failed" });
    await vi.waitFor(() => expect(statuses.at(-1)).toBe("degraded"));
    editor.emit({ objectId: "live-control-0", value: "Latest" });
    await vi.waitFor(() => expect(preview.values.get("wasm-control-0")).toBe("Latest"));
    await vi.waitFor(() => expect(statuses.at(-1)).toBe("ready"));

    expect(statuses.slice(-2)).toEqual(["degraded", "ready"]);
    expect(preview.applied.slice(-2)).toEqual([
      [{ objectId: "wasm-control-0", value: "Failed" }],
      [{ objectId: "wasm-control-0", value: "Latest" }],
    ]);
    sync.dispose();
  });

  it("recovers after every failed control object is synchronized", async () => {
    const editor = new MemoryEndpoint(
      { objectId: "live-control-a", value: "A0" },
      { objectId: "live-control-b", value: "B0" },
      { objectId: "live-control-x", value: "X0" },
    );
    const preview = new DeferredApplyEndpoint(
      { objectId: "wasm-control-a", value: "A0" },
      { objectId: "wasm-control-b", value: "B0" },
      { objectId: "wasm-control-x", value: "X0" },
    );
    const statuses: string[] = [];
    const sync = await synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: { cells: { controls: "live-control" } },
      previewControls: { cells: { controls: "wasm-control" } },
      onStatus: (status) => statuses.push(status.phase),
    });

    editor.emit({ objectId: "live-control-x", value: "X1" });
    editor.emit({ objectId: "live-control-a", value: "A1" });
    editor.emit({ objectId: "live-control-b", value: "B1" });
    preview.resolveNext();
    await vi.waitFor(() => expect(preview.applied).toHaveLength(2));
    expect(preview.applied[1]).toEqual([
      { objectId: "wasm-control-a", value: "A1" },
      { objectId: "wasm-control-b", value: "B1" },
    ]);

    editor.emit({ objectId: "live-control-a", value: "A2" });
    preview.rejectNext();
    await vi.waitFor(() => expect(preview.applied).toHaveLength(3));
    expect(preview.applied[2]).toEqual([{ objectId: "wasm-control-a", value: "A2" }]);
    preview.resolveNext();
    await Promise.resolve();

    expect(statuses).toEqual(["degraded"]);
    await vi.waitFor(() => expect(preview.applied).toHaveLength(4));
    expect(preview.applied[3]).toEqual([{ objectId: "wasm-control-b", value: "B1" }]);
    preview.resolveNext();
    await vi.waitFor(() => expect(statuses).toEqual(["degraded", "ready"]));

    editor.emit({ objectId: "live-control-b", value: "B2" });
    preview.rejectNext();
    await vi.waitFor(() => expect(statuses).toEqual(["degraded", "ready", "degraded"]));
    await vi.waitFor(() => expect(preview.applied).toHaveLength(6));
    expect(preview.applied[5]).toEqual([{ objectId: "wasm-control-b", value: "B2" }]);
    preview.resolveNext();
    await vi.waitFor(() => expect(statuses).toEqual(["degraded", "ready", "degraded", "ready"]));
    sync.dispose();
  });

  it("disconnects endpoints while the initial synchronization is pending", async () => {
    const editor = new MemoryEndpoint({ objectId: "live-control-0", value: "Initial" });
    const preview = new DeferredApplyEndpoint({
      objectId: "wasm-control-0",
      value: "Preview",
    });
    const controller = new AbortController();
    const synchronizing = synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: { cells: { controls: "live-control" } },
      previewControls: { cells: { controls: "wasm-control" } },
      signal: controller.signal,
    });
    await Promise.resolve();

    const cancelled = expect(synchronizing).rejects.toMatchObject({ name: "AbortError" });
    controller.abort();
    editor.emit({ objectId: "live-control-0", value: "After abort" });
    expect(preview.applied).toHaveLength(1);

    await cancelled;
  });
});
