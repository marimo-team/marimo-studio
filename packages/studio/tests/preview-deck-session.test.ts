import { browserObservationSchema } from "@marimo-studio/protocol/browser-observations";
import { afterEach, expect, it, vi } from "vite-plus/test";

import type { RecordBrowserObservation } from "../src/features/preview/observation-remote.ts";

import { PreviewDeck } from "../src/features/preview/deck.ts";
import { emptyProjectionEvidence } from "./fixtures.ts";
import { dispatchPreviewMessage, frame } from "./preview-test-support.ts";

afterEach(() => vi.unstubAllGlobals());

it.each([
  {
    runtime: "server",
    renderedSessionId: "s_rendered",
    expectedSessionId: "s_editor",
  },
  {
    runtime: "wasm",
    renderedSessionId: null,
    expectedSessionId: null,
  },
])(
  "records $runtime observations with their runtime session contract",
  async ({ runtime, renderedSessionId, expectedSessionId }) => {
    const editor = frame("complete");
    const preview = frame("complete");
    const previewWindow = { postMessage: vi.fn() };
    Object.defineProperty(preview, "contentWindow", {
      configurable: true,
      value: previewWindow,
    });
    const record = vi.fn<RecordBrowserObservation>(async () => undefined);
    const deck = new PreviewDeck({
      initialView: "dashboard",
      initialRuntime: runtime,
      initialNavigation: { query: "", hash: "" },
      runtimes: [runtime],
      viewUrl: (view, selectedRuntime) => `/${view}?runtime=${selectedRuntime}`,
      supportUrl: (view) => `/support/${view}`,
      syncQuery: vi.fn(),
      syncEditorQuery: vi.fn(async () => "accepted" as const),
      navigate: vi.fn(),
      recordObservation: record,
    });
    deck.attach(editor, new Map([[runtime, preview]]));
    deck.editorSessionChanged({
      schema: 1,
      generation: 1,
      sessionId: "s_editor",
      replaced: false,
    });
    const lifecycleId = deck.getSnapshot().states[runtime]!.lifecycleId;
    dispatchPreviewMessage(previewWindow, {
      type: "marimo-studio:receiver-ready",
      runtime,
      lifecycleId,
      view: "dashboard",
      revision: "revision-1",
    });
    dispatchPreviewMessage(previewWindow, {
      type: "marimo-studio:view-ready",
      runtime,
      lifecycleId,
      view: "dashboard",
      revision: "revision-1",
    });
    deck.requestObservation({
      schema: 1,
      requestId: "request-dashboard",
      view: "dashboard",
      runtime,
      runtimeInstance: `${runtime}-instance`,
      revision: "revision-1",
    });
    dispatchPreviewMessage(previewWindow, {
      type: "marimo-studio:view-observation",
      lifecycleId,
      requestId: "request-dashboard",
      view: "dashboard",
      runtime,
      runtimeInstance: `${runtime}-instance`,
      revision: "revision-1",
      state: "ready",
      diagnostics: [],
      sessionId: renderedSessionId,
      query: "",
      ...emptyProjectionEvidence,
    });

    await vi.waitFor(() => expect(record).toHaveBeenCalledOnce());
    const observation = record.mock.calls[0]![0];
    const uploaded = browserObservationSchema.parse({
      ...observation,
      schema: 1,
      clientId: "browser-client-1234",
      sequence: 0,
    });
    expect(uploaded.sessionId).toBe(expectedSessionId);
    expect(uploaded.runtimeStatus.sessionId).toBe(expectedSessionId);
    expect(
      uploaded.runtimeStatus.transitions.every(({ sessionId }) => sessionId === expectedSessionId),
    ).toBe(true);
    deck.dispose();
  },
);
