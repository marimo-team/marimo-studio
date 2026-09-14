// @vitest-environment jsdom
import { expect, test, vi } from "vite-plus/test";

import { connectMarimoEditorWorkspace } from "../src/editor-workspace.ts";
import { connectNotebookEntry } from "../src/notebook-entry.ts";

test("keeps native sidebar ownership while the notebook is resized, hidden, and restored", () => {
  let resized = () => {};
  const disconnect = vi.fn();
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(callback: () => void) {
        resized = callback;
      }
      observe() {}
      disconnect = disconnect;
    },
  );
  const frame = document.createElement("iframe");
  document.body.append(frame);
  const doc = frame.contentDocument!;
  doc.body.innerHTML =
    '<aside id="agent">Agent conversation</aside><div id="app-chrome-body"><div id="app"><input value="unsaved draft"></div><div id="app-chrome-panel"></div></div>';
  const app = doc.getElementById("app")!;
  const container = doc.getElementById("app-chrome-body")!;
  const developer = doc.getElementById("app-chrome-panel")!;
  container.getBoundingClientRect = () => new DOMRect(300, 0, 900, 800);
  developer.getBoundingClientRect = () => new DOMRect(300, 800, 900, 0);
  const listener = vi.fn();
  const workspace = connectMarimoEditorWorkspace(frame, listener);
  workspace.placeNotebook({ left: 300, top: 34, width: 450, height: 766 });
  expect(app.style.width).toBe("450px");
  expect(listener).toHaveBeenLastCalledWith({ left: 300, top: 0, width: 900, height: 800 });
  workspace.placeNotebook(undefined);
  expect(app.inert).toBe(true);
  expect(doc.getElementById("agent")!.inert).not.toBe(true);
  container.getBoundingClientRect = () => new DOMRect(400, 0, 800, 800);
  resized();
  expect(listener).toHaveBeenLastCalledWith({ left: 400, top: 0, width: 800, height: 800 });
  workspace.placeNotebook({ left: 400, top: 34, width: 400, height: 766 });
  expect(app.inert).toBe(false);
  expect(app.querySelector("input")!.value).toBe("unsaved draft");
  workspace.close();
  workspace.placeNotebook({ left: 0, top: 0, width: 900, height: 800 });
  resized();
  workspace.close();
  expect(app.style.width).toBe("");
  expect(app.style.borderTop).toBe("");
  expect(disconnect).toHaveBeenCalledOnce();
  frame.remove();
  vi.unstubAllGlobals();
});

test("offers the installed extension only when a native notebook is ready and delegates Save", async () => {
  document.body.replaceChildren();
  const unmount = vi.fn();
  let saveNotebook: (() => void) | undefined;
  const mount = vi.fn((_target: HTMLElement, save: () => void) => {
    saveNotebook = save;
    return unmount;
  });
  const close = connectNotebookEntry(mount);
  expect(mount).not.toHaveBeenCalled();
  const chrome = document.createElement("main");
  chrome.dataset.testid = "chrome-wrapper";
  const button = document.createElement("button");
  button.dataset.testid = "save-button";
  const save = vi.fn();
  button.addEventListener("click", save);
  chrome.append(button);
  document.body.append(chrome);
  await vi.waitFor(() => expect(mount).toHaveBeenCalledOnce());
  saveNotebook?.();
  expect(save).toHaveBeenCalledOnce();
  close();
  close();
  expect(unmount).toHaveBeenCalledOnce();
  expect(document.getElementById("marimo-studio-entry")).toBeNull();
  expect(chrome.style.top).toBe("");
  document.body.replaceChildren();
});
