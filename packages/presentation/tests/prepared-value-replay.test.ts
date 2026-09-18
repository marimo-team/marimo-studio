import {
  mountPreparedPresentation,
  releaseProjectedOutputResources,
} from "@marimo-studio/marimo-frontend/prepared-presentation";
import assert from "node:assert/strict";
import { afterEach, beforeAll, test, vi } from "vite-plus/test";

import type {
  PreparedProjectionHandle,
  PreparedProjectionSnapshot,
} from "../src/prepared/index.ts";

import { createPreparedProjectionMount } from "../src/prepared/controller.tsx";
import { projectionHosts } from "../src/projections/host-runtime.ts";
import { commitRuntimeConfig } from "../src/runtime-config/index.ts";
import { isMarimoValueHost } from "../src/values/hosts.ts";
import {
  preparedPresentation as presentation,
  preparedRuntimeConfig as config,
  preparedTheme as theme,
  settlePreparedRender as settle,
} from "./prepared-fixture.ts";

const snapshot: PreparedProjectionSnapshot = {
  values: [
    {
      selector: "report",
      value: { codec: "json-v1", fingerprint: `sha256:${"a".repeat(64)}`, value: 42 },
    },
  ],
  outputs: [],
  cells: [],
};

const handles: PreparedProjectionHandle[] = [];

beforeAll(() => projectionHosts.register());
afterEach(async () => {
  await Promise.allSettled(handles.splice(0).map((handle) => handle.dispose()));
  projectionHosts.disconnect();
  document.body.replaceChildren();
});

const createHost = (selector = "report", site = "value-report"): HTMLElement => {
  const host = document.createElement("span");
  host.setAttribute("mo-value", selector);
  host.setAttribute("data-marimo-studio-site", site);
  document.body.append(host);
  return host;
};

const mount = (pause?: "before-values" | "after-values") => {
  const entered = Promise.withResolvers<void>();
  const gate = Promise.withResolvers<void>();
  let first = true;
  const wait = async () => {
    entered.resolve();
    await gate.promise;
  };
  const createMount = createPreparedProjectionMount({
    mountPresentation: (options) => {
      const shell = mountPreparedPresentation(options);
      return {
        ...shell,
        models: {
          ...shell.models,
          async replace(resources, signal) {
            const paused = first;
            first = false;
            if (paused && pause === "before-values") await wait();
            const replacement = await shell.models.replace(resources, signal);
            return {
              ...replacement,
              async commit() {
                if (paused && pause === "after-values") await wait();
                await replacement.commit();
              },
            };
          },
        },
      };
    },
    releaseOutputResources: releaseProjectedOutputResources,
  });
  const root = document.createElement("div");
  document.body.append(root);
  const handle = createMount({ root, presentation, theme });
  handles.push(handle);
  return { handle, entered: entered.promise, resume: () => gate.resolve() };
};

test("late value replay survives a queued replacement that aborts before applying", async () => {
  commitRuntimeConfig(config);
  projectionHosts.connect();
  const { handle, entered, resume } = mount("after-values");
  const replacement = handle.replace(snapshot);
  let host: HTMLElement;
  let cancelled: Promise<void>;
  try {
    await entered;
    host = createHost();
    await vi.waitFor(() => assert.equal(host.dataset.state, "connecting"));
    cancelled = assert.rejects(handle.replace(snapshot, { signal: AbortSignal.abort() }));
  } finally {
    resume();
  }
  await replacement;
  await cancelled;
  await vi.waitFor(() => assert.equal(host.dataset.state, "ready"));
  assert.ok(isMarimoValueHost(host));
  assert.equal(host.marimoValue, 42);
  await assert.rejects(handle.replace(snapshot, { signal: AbortSignal.abort() }));
  await vi.waitFor(() => assert.equal(host.dataset.state, "ready"));
  assert.equal(host.marimoValue, 42);
});

test("unrelated value-host activity does not rewrite committed prepared hosts", async () => {
  commitRuntimeConfig({
    ...config,
    projectionRevision: "c".repeat(64),
    mounts: [
      ...config.mounts,
      { ...config.mounts[0]!, id: "other-value", allowedTargets: ["report.total"] },
    ],
  });
  const host = createHost();
  projectionHosts.connect();
  const { handle } = mount();
  await handle.replace(snapshot);
  await settle();
  const mutations: MutationRecord[] = [];
  const observer = new MutationObserver((records) => mutations.push(...records));
  observer.observe(host, { attributes: true, childList: true, subtree: true });
  try {
    const other = createHost("report.total", "other-value");
    await vi.waitFor(() => assert.equal(other.dataset.state, "connecting", other.outerHTML));
    await settle();
    other.remove();
    await vi.waitFor(() => assert.equal(other.dataset.state, undefined));
    await settle();
    assert.equal(mutations.length, 0);
    assert.ok(isMarimoValueHost(host));
    assert.equal(host.marimoValue, 42);
  } finally {
    observer.disconnect();
  }
});

test.each(["before-values", "after-values"] as const)(
  "late replay stays bound to the revision that applied values (%s)",
  async (pause) => {
    commitRuntimeConfig(config);
    projectionHosts.connect();
    const { handle, entered, resume } = mount(pause);
    const replacement = handle.replace(snapshot);
    try {
      await entered;
      commitRuntimeConfig({ ...config, projectionRevision: "b".repeat(64) });
      await settle();
    } finally {
      resume();
    }
    await replacement;
    const host = createHost();
    if (pause === "after-values") {
      await vi.waitFor(() => assert.equal(host.dataset.state, "connecting"));
      await settle();
      assert.ok(isMarimoValueHost(host));
      assert.equal(host.marimoValue, undefined);
      await handle.replace(snapshot);
    }
    await vi.waitFor(() => assert.equal(host.dataset.state, "ready"));
    assert.ok(isMarimoValueHost(host));
    assert.equal(host.marimoValue, 42);
  },
);
