import { describe, expect, it, vi } from "vite-plus/test";

import { synchronizeControlEndpoints } from "../src/features/preview/control-sync.ts";
import {
  controls,
  DeferredApplyEndpoint,
  LocalApplyEndpoint,
  MemoryEndpoint,
  rootBinding,
  SelfBindingEndpoint,
  TransientPeerEndpoint,
} from "./control-sync-fixture.ts";

describe("control writers", () => {
  it("keeps self-authored prepared bindings live across a projection remount", async () => {
    const binding = rootBinding("scale");
    const editor = new MemoryEndpoint({ objectId: "live-scale", value: 3 });
    const preview = new SelfBindingEndpoint(
      { "prepared-scale": binding },
      { objectId: "prepared-scale", value: 3 },
    );
    const sync = await synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: controls({ "live-scale": binding }),
      previewControls: controls({ "prepared-scale": binding }),
    });

    preview.register({ objectId: "prepared-scale", value: 1 });
    preview.emit({ objectId: "prepared-scale", value: 3 });
    await vi.waitFor(() => expect(editor.applied).toHaveLength(2));

    expect(sync.isQuarantined()).toBe(false);
    expect(editor.applied).toEqual([
      [{ objectId: "live-scale", value: 1 }],
      [{ objectId: "live-scale", value: 3 }],
    ]);
    sync.dispose();
  });

  it("keeps initial prepared reconciliation local and commits later editor input", async () => {
    const binding = rootBinding("scale");
    const editor = new MemoryEndpoint({ objectId: "live-scale", value: 2 });
    const preview = new LocalApplyEndpoint(
      { "prepared-scale": binding },
      { objectId: "prepared-scale", value: 1 },
    );
    const sync = await synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: controls({ "live-scale": binding }),
      previewControls: controls({ "prepared-scale": binding }),
    });

    expect(preview.localApplied).toEqual([[{ objectId: "prepared-scale", value: 2 }]]);
    expect(preview.applied).toEqual([]);

    editor.emit({ objectId: "live-scale", value: 3 });
    await vi.waitFor(() => expect(preview.applied).toHaveLength(1));
    expect(preview.applied).toEqual([[{ objectId: "prepared-scale", value: 3 }]]);
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
      editorControls: controls({ "live-control-0": rootBinding("mode") }),
      previewControls: controls({ "wasm-control-0": rootBinding("mode") }),
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

  it("retains the first apply error while draining the latest queued value", async () => {
    const editor = new MemoryEndpoint({ objectId: "live-control-0", value: "Initial" });
    const preview = new DeferredApplyEndpoint({ objectId: "wasm-control-0", value: "Preview" });
    const synchronizing = synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: controls({ "live-control-0": rootBinding("mode") }),
      previewControls: controls({ "wasm-control-0": rootBinding("mode") }),
    });
    await Promise.resolve();
    editor.emit({ objectId: "live-control-0", value: "Latest" });

    const first = new Error("First apply failed");
    preview.rejectNext(first);
    await vi.waitFor(() => expect(preview.applied).toHaveLength(2));
    expect(preview.applied[1]).toEqual([{ objectId: "wasm-control-0", value: "Latest" }]);
    preview.resolveNext();

    await expect(synchronizing).rejects.toBe(first);
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
      editorControls: controls({ "live-control-0": rootBinding("mode") }),
      previewControls: controls({ "wasm-control-0": rootBinding("mode") }),
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

  it("retries a rolled-back peer write from a fresh authoritative snapshot", async () => {
    const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const binding = rootBinding("scale");
    const editor = new MemoryEndpoint({ objectId: "live-scale", value: 1 });
    const preview = new TransientPeerEndpoint({ objectId: "prepared-scale", value: 1 });
    const sync = await synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: controls({ "live-scale": binding }),
      previewControls: controls({ "prepared-scale": binding }),
    });

    editor.emit({ objectId: "live-scale", value: 2 });
    await vi.waitFor(() => expect(preview.applied).toHaveLength(1));
    await vi.waitFor(() => expect(sync.isQuarantined()).toBe(true));

    expect(editor.values.get("live-scale")).toBe(2);
    expect(preview.values.get("prepared-scale")).toBe(1);
    expect(preview.kernelValues.get("prepared-scale")).toBe(1);
    expect(sync.quarantinedSources()).toEqual(new Set(["editor"]));

    await sync.updateControls();

    expect(preview.applied).toHaveLength(2);
    expect(preview.values.get("prepared-scale")).toBe(2);
    expect(preview.kernelValues.get("prepared-scale")).toBe(2);
    expect(sync.isQuarantined()).toBe(false);
    warning.mockRestore();
    sync.dispose();
  });
});
