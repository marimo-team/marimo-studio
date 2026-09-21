// @vitest-environment jsdom
import { expect, test, vi } from "vite-plus/test";

import { connectMarimoEditorWorkspace } from "../src/editor-workspace.ts";
import { connectNotebookEntry } from "../src/notebook-entry.ts";

test("tracks notification bounds through resize, dismissal, and workspace closure", async () => {
  const resized: (() => void)[] = [];
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(callback: () => void) {
        resized.push(callback);
      }
      observe() {}
      disconnect() {}
    },
  );
  const frame = document.createElement("iframe");
  document.body.append(frame);
  const doc = frame.contentDocument!;
  const notification = vi.fn();
  const workspace = connectMarimoEditorWorkspace(frame, vi.fn(), vi.fn(), notification);
  try {
    const viewport = doc.createElement("ol");
    const toast = doc.createElement("li");
    toast.dataset.swipeDirection = "right";
    toast.dataset.state = "open";
    viewport.append(toast);
    let bounds = new DOMRect(600, 650, 400, 150);
    viewport.getBoundingClientRect = () => bounds;
    doc.body.append(viewport);
    await vi.waitFor(() => expect(notification).toHaveBeenLastCalledWith(bounds));
    bounds = new DOMRect(600, 550, 400, 250);
    resized.forEach((resize) => resize());
    expect(notification).toHaveBeenLastCalledWith(bounds);
    toast.dataset.state = "closed";
    await vi.waitFor(() => expect(notification).toHaveBeenLastCalledWith(undefined));
    toast.dataset.state = "open";
    await vi.waitFor(() => expect(notification).toHaveBeenLastCalledWith(bounds));
    workspace.close();
    expect(notification).toHaveBeenLastCalledWith(undefined);
    notification.mockClear();
    resized.forEach((resize) => resize());
    viewport.remove();
    await Promise.resolve();
    expect(notification).not.toHaveBeenCalled();
  } finally {
    workspace.close();
    frame.remove();
    vi.unstubAllGlobals();
  }
});

test("keeps native sidebar ownership while the notebook is resized, hidden, and restored", async () => {
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
  const dialogState = vi.fn();
  const workspace = connectMarimoEditorWorkspace(frame, listener, dialogState, vi.fn());
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
  const dialog = doc.createElement("div");
  dialog.setAttribute("role", "alertdialog");
  dialog.dataset.state = "open";
  doc.body.append(dialog);
  await vi.waitFor(() => expect(dialogState).toHaveBeenLastCalledWith(true));
  dialog.dataset.state = "closed";
  await vi.waitFor(() => expect(dialogState).toHaveBeenLastCalledWith(false));
  const explorer = doc.createElement("div");
  explorer.dataset.testid = "chrome-context-aware-panel";
  doc.body.append(explorer);
  await vi.waitFor(() => expect(dialogState).toHaveBeenLastCalledWith(true));
  explorer.remove();
  await vi.waitFor(() => expect(dialogState).toHaveBeenLastCalledWith(false));
  dialog.dataset.state = "open";
  await vi.waitFor(() => expect(dialogState).toHaveBeenLastCalledWith(true));
  workspace.close();
  expect(dialogState).toHaveBeenLastCalledWith(false);
  workspace.placeNotebook({ left: 0, top: 0, width: 900, height: 800 });
  resized();
  workspace.close();
  expect(app.style.width).toBe("");
  expect(app.style.borderTop).toBe("");
  expect(disconnect).toHaveBeenCalled();
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
