import { requiresPreparedModelRemount } from "@marimo-studio/marimo-frontend/prepared-presentation";
import assert from "node:assert/strict";
import { afterEach, beforeAll, test, vi } from "vite-plus/test";

import type {
  PreparedProjectionHandle,
  PreparedProjectionSnapshot,
} from "../src/prepared/index.ts";

import { mountPreparedProjections } from "../src/prepared/index.ts";
import { projectionHosts } from "../src/projections/host-runtime.ts";
import { commitRuntimeConfig } from "../src/runtime-config/index.ts";
import {
  preparedPresentation as presentation,
  preparedRuntimeConfig as config,
  preparedTheme as theme,
  projectionUiId,
} from "./prepared-fixture.ts";

interface PreparedWidgetLifecycleCounts {
  readonly initialize: Record<string, number>;
  readonly initializeCleanup: Record<string, number>;
  readonly render: Record<string, number>;
  readonly renderCleanup: Record<string, number>;
}

// SAFETY: The test module and widget fixture share this isolated lifecycle counter.
const widgetBrowser = globalThis as typeof globalThis & {
  __activePreparedReplacement?: number;
  __abortPreparedReplacement?: () => void;
  __preparedCheckpointModuleGate?: Promise<void>;
  __preparedCheckpointModuleStarted?: boolean;
  __preparedReplacementOverlap?: boolean;
  __preparedWidgetLifecycle?: PreparedWidgetLifecycleCounts;
};

const widgetLifecycle = (): PreparedWidgetLifecycleCounts => {
  const counts = widgetBrowser.__preparedWidgetLifecycle;
  assert.ok(counts);
  return counts;
};

const widgetModule = `
export default {
  initialize({ model }) {
    const counts = globalThis.__preparedWidgetLifecycle;
    const key = model.get("key");
    counts.initialize[key] = (counts.initialize[key] ?? 0) + 1;
    return () => {
      counts.initializeCleanup[key] = (counts.initializeCleanup[key] ?? 0) + 1;
    };
  },
  render({ model, el }) {
    const counts = globalThis.__preparedWidgetLifecycle;
    const key = model.get("key");
    counts.render[key] = (counts.render[key] ?? 0) + 1;
    const button = document.createElement("button");
    button.dataset.preparedWidget = key;
    const update = () => {
      button.textContent = key + ": " + model.get("value");
    };
    const increment = () => {
      model.set("value", model.get("value") + 1);
      model.save_changes();
    };
    button.addEventListener("click", increment);
    model.on("change:value", update);
    update();
    el.append(button);
    return () => {
      button.removeEventListener("click", increment);
      model.off("change:value", update);
      counts.renderCleanup[key] = (counts.renderCleanup[key] ?? 0) + 1;
    };
  },
};
`;
const widgetModuleUrl = `data:text/javascript,${encodeURIComponent(widgetModule)}`;

const widgetOutput = (selector: string, ownerCellId: string, modelId: string, key: string) => {
  const projectionDigest = modelId.slice("projection-".length, "projection-".length + 64);
  const objectId = `${ownerCellId}-projection-${projectionDigest}-ui-widget`;
  return {
    schema: "marimo.output.v1" as const,
    selector,
    ownerCellId,
    projectionSha256: projectionDigest,
    output: {
      channel: "output" as const,
      mimetype: "text/html",
      data: `<marimo-ui-element object-id="${objectId}"><marimo-anywidget data-initial-value="{}" data-model-id='"${modelId}"'></marimo-anywidget></marimo-ui-element>`,
    },
    resources: {
      files: {},
      modelNotifications: [
        {
          op: "model-lifecycle" as const,
          model_id: modelId,
          message: {
            method: "open" as const,
            state: { key, value: 7 },
            buffer_paths: [],
            buffers: [],
            esm_spec: {
              url: widgetModuleUrl,
              hash: "prepared-two-widget-module-v1",
            },
          },
        },
      ],
      functions: { [objectId]: [] },
      uiValues: { [objectId]: { model_id: modelId } },
    },
  };
};

const widgetSnapshot = (label: string): PreparedProjectionSnapshot => ({
  values: [
    {
      selector: "report",
      value: {
        codec: "json-v1",
        fingerprint: `sha256:${"a".repeat(64)}`,
        value: { label },
      },
    },
  ],
  outputs: [
    widgetOutput(
      "widget.first",
      "prepared-first-widget-output",
      `projection-${"a".repeat(64)}-model-0`,
      "first",
    ),
    widgetOutput(
      "widget.second",
      "prepared-second-widget-output",
      `projection-${"b".repeat(64)}-model-0`,
      "second",
    ),
  ],
  cells: [],
});

const checkpointSnapshot = (
  label: "old" | "next",
  modelDigest: string,
  controlDigest: string,
  controlValue: number,
): PreparedProjectionSnapshot => {
  const widgetOwner = `prepared-checkpoint-${label}-widget`;
  const modelId = `projection-${modelDigest.repeat(64)}-model-0`;
  const controlOwner = `prepared-checkpoint-${label}-control`;
  const controlId = projectionUiId(controlOwner, controlDigest, "slider");
  return {
    values: [
      {
        selector: "report",
        value: {
          codec: "json-v1",
          fingerprint: `sha256:${"a".repeat(64)}`,
          value: { label },
        },
      },
    ],
    outputs: [
      widgetOutput("checkpoint.widget", widgetOwner, modelId, label),
      {
        schema: "marimo.output.v1",
        selector: "checkpoint.control",
        ownerCellId: controlOwner,
        projectionSha256: controlDigest.repeat(64),
        output: {
          channel: "output",
          mimetype: "text/html",
          data: `<marimo-ui-element object-id="${controlId}"><marimo-slider data-initial-value="${controlValue}" data-label="null" data-start="0" data-stop="10" data-steps="null"></marimo-slider></marimo-ui-element>`,
        },
        resources: {
          files: {},
          modelNotifications: [],
          functions: { [controlId]: [] },
          uiValues: { [controlId]: controlValue },
        },
      },
    ],
    cells: [],
  };
};

const handles: PreparedProjectionHandle[] = [];

beforeAll(() => {
  projectionHosts.register();
  Object.defineProperty(globalThis, "matchMedia", {
    configurable: true,
    value: () => ({
      matches: false,
      media: "",
      onchange: null,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
      dispatchEvent: () => false,
    }),
  });
  class TestResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  Object.defineProperty(globalThis, "ResizeObserver", {
    configurable: true,
    value: TestResizeObserver,
  });
});

afterEach(async () => {
  await Promise.allSettled(handles.splice(0).map((handle) => handle.dispose()));
  projectionHosts.disconnect();
  document.head.replaceChildren();
  document.body.replaceChildren();
  delete widgetBrowser.__abortPreparedReplacement;
  delete widgetBrowser.__activePreparedReplacement;
  delete widgetBrowser.__preparedCheckpointModuleGate;
  delete widgetBrowser.__preparedCheckpointModuleStarted;
  delete widgetBrowser.__preparedReplacementOverlap;
  delete widgetBrowser.__preparedWidgetLifecycle;
});

test("prepared widget checkpoints retain browser edits after captured lifecycle updates", async () => {
  commitRuntimeConfig(config);
  document.body.innerHTML = `
    <div id="runtime"></div>
    <marimo-output value="widget.first"></marimo-output>
  `;
  projectionHosts.connect();
  widgetBrowser.__preparedWidgetLifecycle = {
    initialize: {},
    initializeCleanup: {},
    render: {},
    renderCleanup: {},
  };
  const handle = mountPreparedProjections({
    root: document.querySelector<HTMLElement>("#runtime")!,
    presentation,
    theme,
  });
  handles.push(handle);
  const snapshot = widgetSnapshot("sequence");
  const output = snapshot.outputs[0]!;
  const opened = output.resources.modelNotifications[0]!;
  Object.assign(output.resources, {
    modelNotifications: [
      opened,
      {
        ...opened,
        message: {
          method: "update",
          state: { value: 17 },
          buffer_paths: [],
          buffers: [],
          esm_spec: null,
        },
      },
    ],
  });

  await handle.replace(snapshot);

  await vi.waitFor(() => {
    const widget = document.querySelector("marimo-output marimo-anywidget");
    assert.equal(widget?.shadowRoot?.querySelector("button")?.textContent, "first: 17");
  });
  const button = document
    .querySelector("marimo-output marimo-anywidget")!
    .shadowRoot!.querySelector("button")!;
  button.click();
  assert.equal(button.textContent, "first: 18");
  const checkpoint = handle.checkpoint();
  try {
    await handle.replace({ values: [], outputs: [], cells: [] });
    await checkpoint.restore();

    await vi.waitFor(() => {
      const restored = document
        .querySelector("marimo-output marimo-anywidget")
        ?.shadowRoot?.querySelector("button");
      assert.equal(restored?.textContent, "first: 18");
    });
  } finally {
    checkpoint.dispose();
  }
});

test("prepared widget projections preserve browser state through restore and transitions", async () => {
  commitRuntimeConfig(config);
  document.body.innerHTML = `
    <div id="runtime"></div>
    <span id="value" mo-value="report"></span>
    <marimo-output value="widget.first"></marimo-output>
    <marimo-output value="widget.second"></marimo-output>
  `;
  projectionHosts.connect();
  widgetBrowser.__preparedWidgetLifecycle = {
    initialize: {},
    initializeCleanup: {},
    render: {},
    renderCleanup: {},
  };
  const handle = mountPreparedProjections({
    root: document.querySelector<HTMLElement>("#runtime")!,
    presentation,
    theme,
  });
  handles.push(handle);
  await handle.replace(widgetSnapshot("initial"));

  const button = (selector: string): Promise<HTMLButtonElement> =>
    vi.waitFor(() => {
      const host = document.querySelector<HTMLElement>(`marimo-output[value="${selector}"]`);
      const widget = host?.querySelector("marimo-anywidget");
      const current = widget?.shadowRoot?.querySelector<HTMLButtonElement>("button");
      assert.ok(current, `Prepared widget ${selector} did not render`);
      return current;
    });
  const first = await button("widget.first");
  const second = await button("widget.second");
  assert.equal(first.textContent, "first: 7");
  assert.equal(second.textContent, "second: 7");
  first.click();
  assert.equal(first.textContent, "first: 8");
  const checkpoint = handle.checkpoint();

  const unrelated = widgetSnapshot("unrelated");
  await handle.replace({ ...unrelated, outputs: unrelated.outputs.toReversed() });
  assert.equal(await button("widget.first"), first);
  assert.equal(await button("widget.second"), second);
  assert.equal(first.textContent, "first: 8");

  await checkpoint.restore();
  assert.equal(await button("widget.first"), first);
  assert.equal(await button("widget.second"), second);
  assert.equal(first.textContent, "first: 8");
  checkpoint.dispose();

  const restoration = handle.restore();
  assert.equal(handle.restore(), restoration);
  await restoration;
  assert.equal(await button("widget.first"), first);
  assert.equal(first.textContent, "first: 8");

  const failed = structuredClone(widgetSnapshot("failed"));
  Object.assign(failed.outputs[1]!.output!, {
    mimetype: "application/vnd.example.unsupported",
  });
  await assert.rejects(handle.replace(failed));
  assert.equal(await button("widget.first"), first);
  assert.equal(first.textContent, "first: 8");

  const superseded = handle.replace(widgetSnapshot("superseded"));
  const latest = handle.replace(widgetSnapshot("latest"));
  await assert.rejects(superseded, { name: "AbortError" });
  await latest;
  assert.equal(await button("widget.first"), first);
  assert.equal(first.textContent, "first: 8");
  assert.deepEqual(widgetLifecycle(), {
    initialize: { first: 1, second: 1 },
    initializeCleanup: {},
    render: { first: 1, second: 1 },
    renderCleanup: {},
  });

  await handle.dispose();
  assert.deepEqual(widgetLifecycle(), {
    initialize: { first: 1, second: 1 },
    initializeCleanup: { first: 1, second: 1 },
    render: { first: 1, second: 1 },
    renderCleanup: { first: 1, second: 1 },
  });
});

test("prepared checkpoints restore live widget state and UI drafts after different IDs", async () => {
  commitRuntimeConfig(config);
  document.body.innerHTML = `
    <div id="runtime"></div>
    <marimo-output value="checkpoint.widget"></marimo-output>
    <marimo-output value="checkpoint.control"></marimo-output>
  `;
  projectionHosts.connect();
  widgetBrowser.__preparedWidgetLifecycle = {
    initialize: {},
    initializeCleanup: {},
    render: {},
    renderCleanup: {},
  };
  const handle = mountPreparedProjections({
    root: document.querySelector<HTMLElement>("#runtime")!,
    presentation,
    theme,
  });
  handles.push(handle);
  const button = (): Promise<HTMLButtonElement> =>
    vi.waitFor(() => {
      const host = document.querySelector<HTMLElement>('marimo-output[value="checkpoint.widget"]');
      const current = host
        ?.querySelector("marimo-anywidget")
        ?.shadowRoot?.querySelector<HTMLButtonElement>("button");
      assert.ok(current, "Checkpoint widget did not render");
      return current;
    });
  const sliderValue = (expected: string): Promise<HTMLElement> =>
    vi.waitFor(() => {
      const host = document.querySelector<HTMLElement>('marimo-output[value="checkpoint.control"]');
      const slider = host?.querySelector<HTMLElement>("marimo-slider");
      const value = slider?.shadowRoot
        ?.querySelector('[role="slider"]')
        ?.getAttribute("aria-valuenow");
      assert.ok(slider);
      assert.equal(value, expected);
      return slider;
    });

  await handle.replace(checkpointSnapshot("old", "d", "e", 2));
  const oldButton = await button();
  assert.equal(oldButton.textContent, "old: 7");
  oldButton.click();
  assert.equal(oldButton.textContent, "old: 8");
  const oldSlider = await sliderValue("2");
  oldSlider.dispatchEvent(
    new CustomEvent("marimo-value-input", {
      bubbles: true,
      composed: true,
      detail: { element: oldSlider, value: 4 },
    }),
  );
  const checkpoint = handle.checkpoint();

  await handle.replace(checkpointSnapshot("next", "f", "1", 9));
  assert.equal((await button()).textContent, "next: 7");
  await sliderValue("9");
  assert.deepEqual(widgetLifecycle(), {
    initialize: { old: 1, next: 1 },
    initializeCleanup: { old: 1 },
    render: { old: 1, next: 1 },
    renderCleanup: { old: 1 },
  });

  await checkpoint.restore();

  const restoredButton = await button();
  assert.equal(restoredButton.textContent, "old: 8");
  await sliderValue("4");
  assert.deepEqual(widgetLifecycle(), {
    initialize: { old: 2, next: 1 },
    initializeCleanup: { old: 1, next: 1 },
    render: { old: 2, next: 1 },
    renderCleanup: { old: 1, next: 1 },
  });

  checkpoint.dispose();
  await handle.dispose();
  assert.deepEqual(widgetLifecycle(), {
    initialize: { old: 2, next: 1 },
    initializeCleanup: { old: 2, next: 1 },
    render: { old: 2, next: 1 },
    renderCleanup: { old: 2, next: 1 },
  });
});

test("prepared checkpoints reject active AnyWidget replacement and succeed once settled", async () => {
  commitRuntimeConfig(config);
  document.body.innerHTML = `
    <div id="runtime"></div>
    <marimo-output value="checkpoint.widget"></marimo-output>
    <marimo-output value="checkpoint.control"></marimo-output>
  `;
  projectionHosts.connect();
  widgetBrowser.__preparedWidgetLifecycle = {
    initialize: {},
    initializeCleanup: {},
    render: {},
    renderCleanup: {},
  };
  const handle = mountPreparedProjections({
    root: document.querySelector<HTMLElement>("#runtime")!,
    presentation,
    theme,
  });
  handles.push(handle);
  await handle.replace(checkpointSnapshot("old", "3", "4", 2));

  let releaseModule!: () => void;
  widgetBrowser.__preparedCheckpointModuleStarted = false;
  widgetBrowser.__preparedCheckpointModuleGate = new Promise<void>((resolve) => {
    releaseModule = resolve;
  });
  const blocked = checkpointSnapshot("next", "2", "5", 9);
  const notification = blocked.outputs[0]?.resources.modelNotifications[0];
  assert.ok(notification?.message.method === "open");
  Object.assign(notification.message, {
    esm_spec: {
      url: `data:text/javascript,${encodeURIComponent(`
globalThis.__preparedCheckpointModuleStarted = true;
await globalThis.__preparedCheckpointModuleGate;
${widgetModule}
`)}`,
      hash: "prepared-checkpoint-blocked-module",
    },
  });

  const transition = handle.replace(blocked);
  try {
    await vi.waitFor(() => assert.equal(widgetBrowser.__preparedCheckpointModuleStarted, true));
    assert.throws(
      () => handle.checkpoint(),
      /prepared AnyWidget graph replacement is already active/u,
    );
  } finally {
    releaseModule();
  }
  await transition;

  const checkpoint = handle.checkpoint();
  checkpoint.dispose();
});

test("prepared widget replacement loads changed ESM and retains browser state", async () => {
  commitRuntimeConfig(config);
  document.body.innerHTML = `
    <div id="runtime"></div>
    <marimo-output value="widget.replaced"></marimo-output>
  `;
  projectionHosts.connect();
  widgetBrowser.__preparedWidgetLifecycle = {
    initialize: {},
    initializeCleanup: {},
    render: {},
    renderCleanup: {},
  };
  widgetBrowser.__activePreparedReplacement = 0;
  widgetBrowser.__preparedReplacementOverlap = false;
  const handle = mountPreparedProjections({
    root: document.querySelector<HTMLElement>("#runtime")!,
    presentation,
    theme,
  });
  handles.push(handle);
  const modelId = `projection-${"c".repeat(64)}-model-0`;
  const ownerCellId = "prepared-replaced-widget-output";
  const objectId = projectionUiId(ownerCellId, "c", "widget");
  const state = (version: "v1" | "v2"): PreparedProjectionSnapshot => {
    const module = `
const counts = globalThis.__preparedWidgetLifecycle;
export default {
  initialize({ model }) {
    const key = "${version}:" + model.get("key");
    if (globalThis.__activePreparedReplacement > 0) {
      globalThis.__preparedReplacementOverlap = true;
    }
    globalThis.__activePreparedReplacement += 1;
    counts.initialize[key] = (counts.initialize[key] ?? 0) + 1;
    return () => {
      globalThis.__activePreparedReplacement -= 1;
      counts.initializeCleanup[key] = (counts.initializeCleanup[key] ?? 0) + 1;
    };
  },
  render({ model, el }) {
    const key = "${version}:" + model.get("key");
    counts.render[key] = (counts.render[key] ?? 0) + 1;
    const button = document.createElement("button");
    const update = () => {
      button.textContent = "${version}: " + model.get("value");
    };
    const increment = () => {
      model.set("value", model.get("value") + 1);
      model.save_changes();
    };
    button.addEventListener("click", increment);
    model.on("change:value", update);
    update();
    el.append(button);
    return () => {
      button.removeEventListener("click", increment);
      model.off("change:value", update);
      counts.renderCleanup[key] = (counts.renderCleanup[key] ?? 0) + 1;
      globalThis.__abortPreparedReplacement?.();
    };
  },
};
`;
    return {
      values: [],
      outputs: [
        {
          schema: "marimo.output.v1",
          selector: "widget.replaced",
          ownerCellId,
          projectionSha256: "c".repeat(64),
          output: {
            channel: "output",
            mimetype: "text/html",
            data: `<marimo-ui-element object-id="${objectId}"><marimo-anywidget data-initial-value="{}" data-model-id='"${modelId}"'></marimo-anywidget></marimo-ui-element>`,
          },
          resources: {
            files: {},
            modelNotifications: [
              {
                op: "model-lifecycle",
                model_id: modelId,
                message: {
                  method: "open",
                  state: { key: "replacement", value: 7 },
                  buffer_paths: [],
                  buffers: [],
                  esm_spec: {
                    url: `data:text/javascript,${encodeURIComponent(module)}`,
                    hash: `prepared-replacement-${version}`,
                  },
                },
              },
            ],
            functions: { [objectId]: [] },
            uiValues: { [objectId]: { model_id: modelId } },
          },
        },
      ],
      cells: [],
    };
  };
  const button = (): Promise<HTMLButtonElement> =>
    vi.waitFor(() => {
      const widget = document.querySelector("marimo-anywidget");
      const current = widget?.shadowRoot?.querySelector<HTMLButtonElement>("button");
      assert.ok(current, "Prepared replacement widget did not render");
      return current;
    });

  await handle.replace(state("v1"));
  const first = await button();
  assert.equal(first.textContent, "v1: 7");
  first.click();
  assert.equal(first.textContent, "v1: 8");

  const aborted = new AbortController();
  widgetBrowser.__abortPreparedReplacement = () => {
    aborted.abort(new DOMException("replacement aborted", "AbortError"));
  };
  await assert.rejects(
    handle.replace(state("v2"), { signal: aborted.signal }),
    requiresPreparedModelRemount,
  );
  delete widgetBrowser.__abortPreparedReplacement;
  const restored = await button();
  assert.notEqual(restored, first);
  assert.equal(restored.textContent, "v1: 8");
  assert.deepEqual(widgetLifecycle(), {
    initialize: { "v1:replacement": 2 },
    initializeCleanup: { "v1:replacement": 1 },
    render: { "v1:replacement": 2 },
    renderCleanup: { "v1:replacement": 1 },
  });

  await handle.replace(state("v2"));
  const second = await button();
  assert.notEqual(second, restored);
  assert.equal(second.textContent, "v2: 8");
  assert.equal(widgetBrowser.__preparedReplacementOverlap, false);
  assert.deepEqual(widgetLifecycle(), {
    initialize: { "v1:replacement": 2, "v2:replacement": 1 },
    initializeCleanup: { "v1:replacement": 2 },
    render: { "v1:replacement": 2, "v2:replacement": 1 },
    renderCleanup: { "v1:replacement": 2 },
  });

  await handle.dispose();
  assert.equal(widgetBrowser.__activePreparedReplacement, 0);
  assert.deepEqual(widgetLifecycle(), {
    initialize: { "v1:replacement": 2, "v2:replacement": 1 },
    initializeCleanup: { "v1:replacement": 2, "v2:replacement": 1 },
    render: { "v1:replacement": 2, "v2:replacement": 1 },
    renderCleanup: { "v1:replacement": 2, "v2:replacement": 1 },
  });
});
