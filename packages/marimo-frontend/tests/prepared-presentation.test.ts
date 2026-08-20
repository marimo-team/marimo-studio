// @vitest-environment jsdom

import assert from "node:assert/strict";
import { afterEach, test, vi } from "vite-plus/test";

import type {
  MountPreparedPresentationOptions,
  PreparedModelGraphFactory,
  PreparedPresentationHandle,
  PreparedThemeSource,
} from "../src/prepared-presentation.tsx";

import {
  mountPreparedPresentation,
  PreparedModelGraphCheckpoint,
} from "../src/prepared-presentation.tsx";

// SAFETY: The test observes globals owned by the prepared presentation facade.
const browser = globalThis as typeof globalThis & {
  __MARIMO_STATIC__?: { readonly files: Readonly<Record<string, string>> };
  _marimo_private_RuntimeState?: { readonly _sendComponentValues?: unknown };
};

const presentation = {
  appConfig: {},
  configOverrides: {},
  userConfig: {},
};

const mounted: PreparedPresentationHandle[] = [];

const root = (): HTMLElement => {
  const element = document.createElement("div");
  document.body.append(element);
  return element;
};

const stableTheme: PreparedThemeSource = {
  current: () => "light",
  subscribe: () => () => {},
};

const createModelGraph: PreparedModelGraphFactory = (port, initial) => {
  port.setFiles(initial.files);
  const checkpoint = new PreparedModelGraphCheckpoint();
  return {
    checkpoint: () => checkpoint,
    replace: async () => ({
      mutated: false,
      remount: false,
      commit: async () => {},
      rollback: async () => {},
    }),
    dispose: async () => {},
  };
};

const mount = (
  options: Omit<MountPreparedPresentationOptions, "createModelGraph">,
): PreparedPresentationHandle => mountPreparedPresentation({ ...options, createModelGraph });

const runtimeState = () => browser._marimo_private_RuntimeState;

afterEach(async () => {
  await Promise.allSettled(mounted.splice(0).map((handle) => handle.dispose()));
  vi.restoreAllMocks();
  document.body.replaceChildren();
  delete browser.__MARIMO_STATIC__;
  delete browser._marimo_private_RuntimeState;
});

test("presentation initialization preserves upstream custom-element move contracts", () => {
  const defineProperty = vi.spyOn(Object, "defineProperty");
  const handle = mount({
    root: root(),
    presentation,
    theme: stableTheme,
  });
  mounted.push(handle);

  assert.equal(
    defineProperty.mock.calls.some(([_target, property]) => property === "connectedMoveCallback"),
    false,
  );
});

test("theme setup failure releases prepared ownership before an immediate retry", async () => {
  browser.__MARIMO_STATIC__ = {
    files: { "existing.js": "data:text/javascript,export default {}" },
  };
  const setupError = new Error("theme subscription failed");
  const failingTheme: PreparedThemeSource = {
    current: () => "light",
    subscribe: () => {
      throw setupError;
    },
  };

  assert.throws(
    () =>
      mount({
        root: root(),
        presentation,
        theme: failingTheme,
      }),
    setupError,
  );

  const retry = mount({
    root: root(),
    presentation,
    theme: stableTheme,
  });
  mounted.push(retry);
  assert.deepEqual(browser.__MARIMO_STATIC__?.files, {
    "existing.js": "data:text/javascript,export default {}",
  });
});

test("control bridge setup failure restores resources before an immediate retry", async () => {
  browser.__MARIMO_STATIC__ = {
    files: { "existing.js": "data:text/javascript,export default {}" },
  };
  const setupError = new Error("control subscription failed");
  const addEventListener = document.addEventListener.bind(document);
  vi.spyOn(document, "addEventListener").mockImplementation((type, listener, options) => {
    if (type === "marimo-value-input") {
      throw setupError;
    }
    addEventListener(type, listener, options);
  });
  const failedRoot = root();

  assert.throws(
    () =>
      mount({
        root: failedRoot,
        presentation,
        theme: stableTheme,
        onControlInput: () => {},
      }),
    setupError,
  );
  vi.restoreAllMocks();
  assert.equal(browser._marimo_private_RuntimeState, undefined);
  assert.equal(failedRoot.childNodes.length, 0);

  const retry = mount({
    root: root(),
    presentation,
    theme: stableTheme,
    onControlInput: () => {},
  });
  assert.ok(runtimeState()?._sendComponentValues);
  await retry.dispose();
  assert.equal(browser._marimo_private_RuntimeState, undefined);
  assert.deepEqual(browser.__MARIMO_STATIC__?.files, {
    "existing.js": "data:text/javascript,export default {}",
  });
});

test("prepared presentations reject roots from another document", () => {
  const ownerDocument = document.implementation.createHTMLDocument("prepared-secondary");
  const mountedRoot = ownerDocument.createElement("div");
  ownerDocument.body.append(mountedRoot);
  assert.throws(
    () =>
      mount({
        root: mountedRoot,
        presentation,
        theme: stableTheme,
      }),
    /root in the current document/u,
  );
});
