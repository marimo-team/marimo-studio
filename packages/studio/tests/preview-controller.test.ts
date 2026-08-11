import { expect, it, vi } from "vite-plus/test";

import { PreviewController } from "../src/features/preview/controller.ts";
import { PreviewDeck } from "../src/features/preview/deck.ts";

const frame = (readyState: DocumentReadyState): HTMLIFrameElement => {
  const element = document.createElement("iframe");
  Object.defineProperty(element, "contentDocument", {
    configurable: true,
    value: { readyState },
  });
  Object.defineProperty(element, "contentWindow", {
    configurable: true,
    value: null,
  });
  element.src = "/loaded";
  return element;
};

const controller = (
  runtime: string,
  editor: HTMLIFrameElement,
  preview: HTMLIFrameElement,
  viewUrl: (view: string, runtime: string) => string,
) =>
  new PreviewController(
    "dashboard",
    runtime,
    editor,
    preview,
    viewUrl,
    (view) => `/support/${view}`,
    vi.fn(),
    vi.fn(async () => "accepted" as const),
    vi.fn(),
    vi.fn(),
  );

it("reloads every preview after its editor session binding changes", () => {
  const editor = frame("loading");
  const serverFrame = frame("complete");
  const wasmFrame = frame("complete");
  const viewUrl = vi.fn((view: string, runtime: string) => `/${view}?runtime=${runtime}`);
  const server = controller("server", editor, serverFrame, viewUrl);
  const wasm = controller("wasm", editor, wasmFrame, viewUrl);
  expect(viewUrl).toHaveBeenCalledTimes(2);

  editor.dispatchEvent(new Event("load"));
  expect(viewUrl).toHaveBeenCalledTimes(2);
  editor.dispatchEvent(new Event("load"));
  expect(viewUrl).toHaveBeenCalledTimes(2);

  server.editorSessionChanged();
  wasm.editorSessionChanged();

  expect(viewUrl).toHaveBeenCalledTimes(4);
  expect(serverFrame.src).toContain("runtime=server");
  expect(wasmFrame.src).toContain("runtime=wasm");
  server.dispose();
  wasm.dispose();
});

it("reloads attached previews once for each newer editor binding", () => {
  const editor = frame("loading");
  const serverFrame = frame("complete");
  const wasmFrame = frame("complete");
  const viewUrl = vi.fn((view: string, runtime: string) => `/${view}?runtime=${runtime}`);
  const deck = new PreviewDeck({
    initialView: "dashboard",
    initialRuntime: "server",
    runtimes: ["server", "wasm"],
    viewUrl,
    supportUrl: (view) => `/support/${view}`,
    syncQuery: vi.fn(),
    syncEditorQuery: vi.fn(async () => "accepted" as const),
    navigate: vi.fn(),
  });
  deck.attach(
    editor,
    new Map([
      ["server", serverFrame],
      ["wasm", wasmFrame],
    ]),
  );
  deck.switchRuntime("wasm");
  expect(viewUrl).toHaveBeenCalledTimes(4);

  deck.editorSessionChanged({
    schema: 1,
    generation: 7,
    sessionId: "s_initial",
    replaced: false,
  });
  deck.editorSessionChanged({
    schema: 1,
    generation: 6,
    sessionId: "s_stale",
    replaced: false,
  });
  expect(viewUrl).toHaveBeenCalledTimes(4);

  deck.editorSessionChanged({
    schema: 1,
    generation: 8,
    sessionId: "s_reconnected",
    replaced: true,
  });
  expect(viewUrl).toHaveBeenCalledTimes(6);
  expect(serverFrame.src).toContain("runtime=server");
  expect(wasmFrame.src).toContain("runtime=wasm");
  deck.dispose();
});
