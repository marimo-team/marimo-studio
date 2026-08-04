import { describe, expect, it } from "vite-plus/test";

import {
  type ControlEndpoint,
  type ControlUpdate,
  synchronizeControlEndpoints,
} from "../src/preview/control-sync";

class MemoryEndpoint implements ControlEndpoint {
  readonly values = new Map<string, unknown>();
  readonly applied: (readonly ControlUpdate[])[] = [];
  private readonly listeners = new Set<(update: ControlUpdate) => void>();

  constructor(values: Record<string, unknown>) {
    Object.entries(values).forEach(([key, value]) => this.values.set(key, value));
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

describe("control state synchronization", () => {
  it("translates stable cell identities between independent runtimes", async () => {
    const editor = new MemoryEndpoint({ "live-control-0": ["Growth"] });
    const preview = new MemoryEndpoint({ "wasm-shifted-control-0": ["Base"] });
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
    const editor = new MemoryEndpoint({
      "live-known-0": 2,
      "live-private-0": 3,
    });
    const preview = new MemoryEndpoint({ "wasm-known-0": 1 });
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
});
