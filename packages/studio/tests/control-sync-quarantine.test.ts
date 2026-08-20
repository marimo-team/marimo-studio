import type { RuntimeControlBinding } from "@marimo-studio/protocol/runtime-config";

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

describe("control quarantine", () => {
  it("quarantines a reused native ID until composite bindings are refreshed", async () => {
    const root = rootBinding("filters");
    const dictionary: RuntimeControlBinding = {
      input: "filters",
      path: [{ kind: "element" }],
    };
    const region: RuntimeControlBinding = {
      input: "filters",
      path: [{ kind: "element" }, { kind: "key", value: "region" }],
    };
    const detail: RuntimeControlBinding = {
      input: "filters",
      path: [{ kind: "element" }, { kind: "key", value: "detail" }],
    };
    const editor = new MemoryEndpoint(
      { objectId: "live-dictionary", value: { region: ["Europe"] } },
      { objectId: "live-reused", value: null },
      { objectId: "live-region", value: ["Europe"] },
    );
    const preview = new MemoryEndpoint(
      { objectId: "prepared-a-root", value: null },
      { objectId: "prepared-b-root", value: null },
      { objectId: "prepared-a-detail", value: "ready" },
      { objectId: "prepared-b-detail", value: "ready" },
    );
    const stale = await synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: controls({
        "live-dictionary": dictionary,
        "live-reused": root,
        "live-region": region,
      }),
      previewControls: controls({
        "prepared-a-root": root,
        "prepared-b-root": root,
        "prepared-a-detail": detail,
        "prepared-b-detail": detail,
      }),
    });

    editor.register({ objectId: "live-new-dictionary", value: { detail: "ready" } });
    editor.emit({ objectId: "live-reused", value: ["Europe"] });

    expect(stale.isQuarantined()).toBe(true);
    expect(stale.quarantinedSources()).toEqual(new Set(["editor"]));
    expect(preview.applied).toEqual([]);
    expect(preview.values.get("prepared-a-root")).toBeNull();
    expect(preview.values.get("prepared-b-root")).toBeNull();
    await stale.updateControls({
      editor: controls({
        "live-root": root,
        "live-new-dictionary": dictionary,
        "live-reused": region,
        "live-detail": detail,
      }),
    });
    editor.emit({ objectId: "live-detail", value: "from editor" });
    await Promise.resolve();

    expect(preview.applied).toEqual([
      [
        { objectId: "prepared-a-detail", value: "from editor" },
        { objectId: "prepared-b-detail", value: "from editor" },
      ],
    ]);
    stale.dispose();
  });

  it("replays matching controls while retaining bindings that are still emerging", async () => {
    const scale = rootBinding("scale");
    const detail = rootBinding("detail");
    const editor = new MutableBindingEndpoint(undefined, {
      objectId: "live-scale",
      value: 1,
    });
    const preview = new MutableBindingEndpoint(
      { "prepared-scale": scale },
      { objectId: "prepared-scale", value: 1 },
      { objectId: "prepared-detail", value: "ready" },
    );
    const sync = await synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: controls({ "live-scale": scale }),
      previewControls: controls({ "prepared-scale": scale }),
    });

    editor.setBindings({ "live-scale": scale });
    preview.setBindings({ "prepared-scale": scale, "prepared-detail": detail });
    editor.topology("live-scale");
    preview.emit({ objectId: "prepared-scale", value: 3 });
    preview.emit({ objectId: "prepared-detail", value: "from preview" });

    await sync.updateControls({
      editor: controls({ "live-scale": scale }),
      preview: controls({ "prepared-scale": scale, "prepared-detail": detail }),
    });

    expect(editor.applied).toEqual([[{ objectId: "live-scale", value: 3 }]]);
    expect(sync.isQuarantined()).toBe(true);

    await sync.updateControls({
      editor: controls({ "live-scale": scale, "live-detail": detail }),
      preview: controls({ "prepared-scale": scale, "prepared-detail": detail }),
    });

    expect(editor.applied).toEqual([
      [{ objectId: "live-scale", value: 3 }],
      [{ objectId: "live-detail", value: "from preview" }],
    ]);
    expect(sync.isQuarantined()).toBe(false);
    sync.dispose();
  });

  it("replays against the configured pair while one live topology is transient", async () => {
    const binding = rootBinding("filters");
    const editor = new MutableBindingEndpoint(undefined, {
      objectId: "live-filters",
      value: null,
    });
    const preview = new MutableBindingEndpoint(
      { "prepared-filters": binding },
      { objectId: "prepared-filters", value: null },
    );
    const configuredEditor = controls({ "live-filters": binding });
    const configuredPreview = controls({ "prepared-filters": binding });
    const sync = await synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: configuredEditor,
      previewControls: configuredPreview,
    });

    editor.setBindings({ "live-filters": binding });
    preview.setBindings({});
    editor.topology("live-filters");
    editor.emit({ objectId: "live-filters", value: { region: "emea" } });

    await sync.updateControls({ editor: configuredEditor, preview: configuredPreview });

    expect(preview.values.get("prepared-filters")).toEqual({ region: "emea" });
    expect(sync.isQuarantined()).toBe(false);
    sync.dispose();
  });

  it("replays a captured semantic binding after its source object ID is replaced", async () => {
    const binding = rootBinding("filters");
    const editor = new MutableBindingEndpoint(undefined, {
      objectId: "live-old",
      value: null,
    });
    const preview = new MutableBindingEndpoint(
      { "prepared-filters": binding },
      { objectId: "prepared-filters", value: null },
    );
    const sync = await synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: controls({ "live-old": binding }),
      previewControls: controls({ "prepared-filters": binding }),
    });

    editor.setBindings({ "live-submitted": binding });
    editor.topology("live-submitted");
    editor.emit({ objectId: "live-submitted", value: { region: "emea" } });
    editor.setBindings({});

    await sync.updateControls({
      editor: controls({ "live-current": binding }),
      preview: controls({ "prepared-filters": binding }),
    });

    expect(preview.values.get("prepared-filters")).toEqual({ region: "emea" });
    expect(sync.isQuarantined()).toBe(false);
    sync.dispose();
  });

  it("keeps captured input when a later invalidation snapshots the same source", async () => {
    const binding = rootBinding("filters");
    const editor = new MutableBindingEndpoint(undefined, {
      objectId: "live-old",
      value: null,
    });
    const preview = new MutableBindingEndpoint(
      { "prepared-filters": binding },
      { objectId: "prepared-filters", value: null },
    );
    const sync = await synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: controls({ "live-old": binding }),
      previewControls: controls({ "prepared-filters": binding }),
    });

    editor.setBindings({ "live-submitted": binding });
    editor.topology("live-submitted");
    editor.emit({ objectId: "live-submitted", value: { region: "emea" } });
    editor.setBindings({});
    sync.invalidateControls("editor");

    await sync.updateControls({
      editor: controls({ "live-current": binding }),
      preview: controls({ "prepared-filters": binding }),
    });

    expect(preview.values.get("prepared-filters")).toEqual({ region: "emea" });
    expect(sync.isQuarantined()).toBe(false);
    sync.dispose();
  });

  it("lets an authoritative snapshot supersede a buffered registration", async () => {
    const binding = rootBinding("filters");
    const editor = new MutableBindingEndpoint(
      { "live-filters": binding },
      { objectId: "live-filters", value: { region: "initial" } },
    );
    const preview = new MutableBindingEndpoint(
      { "prepared-filters": binding },
      { objectId: "prepared-filters", value: { region: "initial" } },
    );
    const sync = await synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: controls({ "live-filters": binding }),
      previewControls: controls({ "prepared-filters": binding }),
    });

    sync.invalidateControls("editor");
    editor.register({ objectId: "live-filters", value: { region: "registration" } });
    editor.values.set("live-filters", { region: "snapshot" });
    await sync.updateControls();

    expect(preview.values.get("prepared-filters")).toEqual({ region: "snapshot" });
    expect(sync.isQuarantined()).toBe(false);
    sync.dispose();
  });

  it("does not retain a failed registration after source invalidation", async () => {
    const binding = rootBinding("filters");
    const editor = new MutableBindingEndpoint({ "live-filters": binding });
    const preview = new DeferredApplyEndpoint({
      objectId: "prepared-filters",
      value: { region: "initial" },
    });
    const sync = await synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: controls({ "live-filters": binding }),
      previewControls: controls({ "prepared-filters": binding }),
    });
    sync.invalidateControls();
    editor.register({ objectId: "live-filters", value: { region: "registration" } });

    const failed = sync.updateControls();
    await vi.waitFor(() => expect(preview.applied).toHaveLength(1));
    sync.invalidateControls("editor");
    editor.values.set("live-filters", { region: "snapshot" });
    preview.rejectNext(new Error("registration apply failed"));
    await expect(failed).rejects.toThrow("registration apply failed");

    const recovered = sync.updateControls();
    await vi.waitFor(() => expect(preview.applied).toHaveLength(2));
    preview.resolveNext();
    await recovered;

    expect(preview.values.get("prepared-filters")).toEqual({ region: "snapshot" });
    expect(sync.isQuarantined()).toBe(false);
    sync.dispose();
  });

  it("keeps inherited object keys local during quarantined replay", async () => {
    const editor = new MutableBindingEndpoint({}, { objectId: "toString", value: "local" });
    const preview = new MutableBindingEndpoint({});
    const sync = await synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: controls({}),
      previewControls: controls({}),
    });

    sync.invalidateControls();
    editor.emit({ objectId: "toString", value: "changed" });

    await expect(sync.updateControls()).resolves.toBeUndefined();
    expect(preview.applied).toEqual([]);
    expect(sync.isQuarantined()).toBe(false);
    sync.dispose();
  });

  it("retries a buffered input after its target write fails", async () => {
    const binding = rootBinding("scale");
    const editor = new RejectOnceBindingEndpoint(
      { "live-scale": binding },
      { objectId: "live-scale", value: 1 },
    );
    const preview = new MutableBindingEndpoint(
      { "prepared-scale": binding },
      { objectId: "prepared-scale", value: 1 },
    );
    const sync = await synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: controls({ "live-scale": binding }),
      previewControls: controls({ "prepared-scale": binding }),
    });

    sync.invalidateControls();
    preview.emit({ objectId: "prepared-scale", value: 3 });
    const failure = new Error("editor update failed");
    editor.failNext(failure);

    await expect(sync.updateControls()).rejects.toBe(failure);
    expect(sync.isQuarantined()).toBe(true);

    await sync.updateControls();

    expect(editor.values.get("live-scale")).toBe(3);
    expect(editor.applied).toEqual([
      [{ objectId: "live-scale", value: 3 }],
      [{ objectId: "live-scale", value: 3 }],
    ]);
    expect(sync.isQuarantined()).toBe(false);
    sync.dispose();
  });

  it("keeps a newer buffered input when an older target write fails", async () => {
    const binding = rootBinding("scale");
    const editor = new DeferredApplyEndpoint({ objectId: "live-scale", value: 1 });
    const preview = new MemoryEndpoint({ objectId: "prepared-scale", value: 1 });
    const sync = await synchronizeControlEndpoints({
      editor,
      preview,
      editorControls: controls({ "live-scale": binding }),
      previewControls: controls({ "prepared-scale": binding }),
    });

    sync.invalidateControls();
    preview.emit({ objectId: "prepared-scale", value: 2 });
    const updating = sync.updateControls();
    await vi.waitFor(() => expect(editor.applied).toHaveLength(1));
    preview.emit({ objectId: "prepared-scale", value: 3 });
    const failure = new Error("first editor update failed");
    editor.rejectNext(failure);

    await expect(updating).rejects.toBe(failure);

    const retrying = sync.updateControls();
    await vi.waitFor(() => expect(editor.applied).toHaveLength(2));
    editor.resolveNext();
    await retrying;

    expect(editor.applied).toEqual([
      [{ objectId: "live-scale", value: 2 }],
      [{ objectId: "live-scale", value: 3 }],
    ]);
    expect(editor.values.get("live-scale")).toBe(3);
    sync.dispose();
  });
});
