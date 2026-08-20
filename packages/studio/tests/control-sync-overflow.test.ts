import { describe, expect, it, vi } from "vite-plus/test";

import { synchronizeControlEndpoints } from "../src/features/preview/control-sync.ts";
import {
  controls,
  DeferredApplyEndpoint,
  MemoryEndpoint,
  MutableBindingEndpoint,
  RejectOnceBindingEndpoint,
  rootBinding,
} from "./control-sync-fixture.ts";

describe("control overflow recovery", () => {
  it("bounds quarantine memory and reconciles every current control from a snapshot", async () => {
    const triggerBinding = rootBinding("trigger");
    const editor = new MemoryEndpoint({ objectId: "live-trigger", value: 0 });
    const preview = new MemoryEndpoint({ objectId: "prepared-mode", value: 0 });
    const sync = await synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: controls({ "live-trigger": triggerBinding }),
      previewControls: controls({ "prepared-mode": triggerBinding }),
    });
    editor.register({ objectId: "live-trigger", value: 0 });
    const editorBindings = Object.fromEntries(
      Array.from({ length: 1_000 }, (_, index) => [`live-${index}`, rootBinding(`mode-${index}`)]),
    );
    const previewBindings = Object.fromEntries(
      Array.from({ length: 1_000 }, (_, index) => [
        `prepared-${index}`,
        rootBinding(`mode-${index}`),
      ]),
    );
    Object.keys(editorBindings).forEach((objectId, value) => {
      editor.emit({ objectId, value });
    });
    editor.emit({ objectId: "live-hot", value: 4_999 });
    const oversized = "x".repeat(16 * 1024 * 1024 + 1);
    editor.emit({ objectId: "live-oversized", value: oversized });

    await sync.updateControls({
      editor: controls({
        ...editorBindings,
        "live-hot": rootBinding("hot"),
        "live-oversized": rootBinding("oversized"),
      }),
      preview: controls({
        ...previewBindings,
        "prepared-hot": rootBinding("hot"),
        "prepared-oversized": rootBinding("oversized"),
      }),
    });

    const applied = preview.applied.flat();
    expect(applied).toHaveLength(1_002);
    expect(preview.applied.every((updates) => updates.length <= 256)).toBe(true);
    expect(applied.filter(({ objectId }) => objectId === "prepared-hot")).toEqual([
      { objectId: "prepared-hot", value: 4_999 },
    ]);
    expect(preview.values.get("prepared-0")).toBe(0);
    expect(preview.values.get("prepared-999")).toBe(999);
    expect(preview.values.get("prepared-oversized")).toBe(oversized);
    sync.dispose();
  });

  it("retains an incomplete overflow snapshot until its semantic target appears", async () => {
    const editorBindings = Object.fromEntries(
      Array.from({ length: 256 }, (_, index) => [`live-${index}`, rootBinding(`mode_${index}`)]),
    );
    const partialEditorBindings = Object.fromEntries(Object.entries(editorBindings).slice(0, 255));
    const previewBindings = Object.fromEntries(
      Array.from({ length: 256 }, (_, index) => [
        `prepared-${index}`,
        rootBinding(`mode_${index}`),
      ]),
    );
    const editor = new RejectOnceBindingEndpoint(
      undefined,
      ...Array.from({ length: 256 }, (_, index) => ({
        objectId: `live-${index}`,
        value: index,
      })),
    );
    const preview = new MutableBindingEndpoint(
      previewBindings,
      ...Array.from({ length: 256 }, (_, index) => ({
        objectId: `prepared-${index}`,
        value: index === 255 ? 999 : index,
      })),
      { objectId: "prepared-private", value: "local" },
    );
    const sync = await synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: controls(editorBindings),
      previewControls: controls(previewBindings),
    });

    preview.values.set("prepared-255", 999);
    editor.setBindings(partialEditorBindings);
    editor.topology("live-255");
    preview.snapshot().forEach((update) => preview.emit(update));
    await sync.updateControls({
      editor: controls(partialEditorBindings),
      preview: controls(previewBindings),
    });

    expect(sync.isQuarantined()).toBe(true);

    const failure = new Error("snapshot apply failed");
    editor.failNext(failure);
    await expect(
      sync.updateControls({
        editor: controls(editorBindings),
        preview: controls(previewBindings),
      }),
    ).rejects.toBe(failure);
    expect(sync.isQuarantined()).toBe(true);

    await sync.updateControls({
      editor: controls(editorBindings),
      preview: controls(previewBindings),
    });

    expect(editor.values.get("live-255")).toBe(999);
    expect(editor.values.has("prepared-private")).toBe(false);
    expect(sync.isQuarantined()).toBe(false);
    sync.dispose();
  });

  it("replays updates that arrive while an overflow snapshot is applying", async () => {
    const triggerBinding = rootBinding("trigger");
    const editor = new MemoryEndpoint({ objectId: "live-trigger", value: 0 });
    const preview = new DeferredApplyEndpoint({ objectId: "prepared-trigger", value: 0 });
    const sync = await synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: controls({ "live-trigger": triggerBinding }),
      previewControls: controls({ "prepared-trigger": triggerBinding }),
    });
    const editorBindings = Object.fromEntries(
      Array.from({ length: 257 }, (_, index) => [`live-${index}`, rootBinding(`mode-${index}`)]),
    );
    const previewBindings = Object.fromEntries(
      Array.from({ length: 257 }, (_, index) => [
        `prepared-${index}`,
        rootBinding(`mode-${index}`),
      ]),
    );
    editor.register({ objectId: "live-trigger", value: 0 });
    Object.keys(editorBindings).forEach((objectId, value) => {
      editor.emit({ objectId, value });
    });

    const updating = sync.updateControls({
      editor: controls(editorBindings),
      preview: controls(previewBindings),
    });
    await vi.waitFor(() => expect(preview.applied).toHaveLength(1));
    editor.emit({ objectId: "live-0", value: 9_999 });
    preview.resolveNext();
    await vi.waitFor(() => expect(preview.applied).toHaveLength(2));
    preview.resolveNext();
    await vi.waitFor(() => expect(preview.applied).toHaveLength(3));
    expect(preview.applied[2]).toEqual([{ objectId: "prepared-0", value: 9_999 }]);
    preview.resolveNext();
    await updating;

    expect(preview.values.get("prepared-0")).toBe(9_999);
    sync.dispose();
  });

  it("restarts authoritative reconciliation when buffered replay overflows", async () => {
    const triggerBinding = rootBinding("trigger");
    const editor = new MemoryEndpoint({ objectId: "live-trigger", value: 0 });
    const preview = new DeferredApplyEndpoint({ objectId: "prepared-trigger", value: 0 });
    const sync = await synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: controls({ "live-trigger": triggerBinding }),
      previewControls: controls({ "prepared-trigger": triggerBinding }),
    });
    const editorBindings = Object.fromEntries(
      Array.from({ length: 257 }, (_, index) => [`live-${index}`, rootBinding(`mode-${index}`)]),
    );
    const previewBindings = Object.fromEntries(
      Array.from({ length: 257 }, (_, index) => [
        `prepared-${index}`,
        rootBinding(`mode-${index}`),
      ]),
    );
    editor.register({ objectId: "live-trigger", value: 0 });
    editor.emit({ objectId: "live-0", value: 1 });
    const updating = sync.updateControls({
      editor: controls(editorBindings),
      preview: controls(previewBindings),
    });
    await vi.waitFor(() => expect(preview.applied).toHaveLength(1));
    Object.keys(editorBindings).forEach((objectId, value) => {
      editor.emit({ objectId, value });
    });

    preview.resolveNext();
    await updating;
    expect(sync.isQuarantined()).toBe(true);

    const reconciling = sync.updateControls({
      editor: controls(editorBindings),
      preview: controls(previewBindings),
    });
    await vi.waitFor(() => expect(preview.applied).toHaveLength(2));
    preview.resolveNext();
    await vi.waitFor(() => expect(preview.applied).toHaveLength(3));
    preview.resolveNext();
    await reconciling;

    expect(preview.values.get("prepared-0")).toBe(0);
    expect(preview.values.get("prepared-256")).toBe(256);
    expect(sync.isQuarantined()).toBe(false);
    sync.dispose();
  });
});
