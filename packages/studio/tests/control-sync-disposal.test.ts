import { describe, expect, it } from "vite-plus/test";

import { synchronizeControlEndpoints } from "../src/features/preview/control-sync.ts";
import {
  controls,
  DeferredApplyEndpoint,
  MemoryEndpoint,
  rootBinding,
} from "./control-sync-fixture.ts";

describe("control synchronization disposal", () => {
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
      editorControls: controls({ "live-control-0": rootBinding("mode") }),
      previewControls: controls({ "wasm-control-0": rootBinding("mode") }),
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
