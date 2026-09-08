import type { PreparedPresentationHandle } from "@marimo-studio/marimo-frontend/prepared-presentation";

import { releaseProjectedOutputResources as releaseMarimoOutputResources } from "@marimo-studio/marimo-frontend/prepared-presentation";
import assert from "node:assert/strict";
import { isValidElement } from "react";
import { afterEach, beforeAll, test, vi } from "vite-plus/test";

import type { PreparedProjectionDependencies } from "../src/prepared/controller.tsx";
import type {
  PreparedProjectionHandle,
  PreparedProjectionSnapshot,
} from "../src/prepared/index.ts";
import type { MarimoValueHost } from "../src/values/hosts.ts";

import { createPreparedProjectionMount } from "../src/prepared/controller.tsx";
import {
  mountPreparedProjections,
  PreparedProjectionCapabilityError,
} from "../src/prepared/index.ts";
import { projectionHosts } from "../src/projections/host-runtime.ts";
import { commitRuntimeConfig } from "../src/runtime-config/index.ts";
import {
  preparedPresentation as presentation,
  preparedResources as resources,
  preparedRuntimeConfig as config,
  preparedTheme as theme,
  projectionUiId,
  settlePreparedRender as settle,
} from "./prepared-fixture.ts";

const snapshot = (label: string): PreparedProjectionSnapshot => ({
  values: [
    {
      selector: "report",
      value: {
        codec: "json-v1",
        fingerprint: `sha256:${"a".repeat(64)}`,
        value: { label, total: 42 },
      },
    },
  ],
  outputs: [
    {
      schema: "marimo.output.v1",
      selector: "report.output",
      ownerCellId: "prepared-report-output",
      projectionSha256: "d".repeat(64),
      output: { channel: "output", mimetype: "text/plain", data: `output ${label}` },
      resources: resources(),
    },
    {
      schema: "marimo.output.v1",
      selector: "report.bundle",
      ownerCellId: "prepared-report-bundle",
      projectionSha256: "e".repeat(64),
      output: {
        channel: "output",
        mimetype: "application/vnd.marimo+mimebundle",
        data: {
          "application/json": { label },
          "text/plain": `bundle ${label}`,
        },
      },
      resources: resources(),
    },
    {
      schema: "marimo.output.v1",
      selector: "report.failure",
      ownerCellId: "prepared-report-failure",
      projectionSha256: "f".repeat(64),
      output: {
        channel: "marimo-error",
        mimetype: "application/vnd.marimo+error",
        data: [
          {
            type: "exception",
            msg: `failure ${label}`,
            exception_type: "RuntimeError",
            raising_cell: "prepared-report-failure",
          },
        ],
      },
      resources: resources(),
    },
  ],
  cells: [
    {
      schema: "marimo.cell.v1",
      alias: "summary",
      projectionSha256: "a".repeat(64),
      cell: {
        id: "prepared-summary-cell",
        name: "summary",
        codeSha256: "a".repeat(64),
        config: {},
      },
      outcome: "completed",
      console: [{ channel: "stdout", mimetype: "text/plain", data: `console ${label}` }],
      output: { channel: "output", mimetype: "text/html", data: `<strong>cell ${label}</strong>` },
      resources: resources(),
    },
  ],
});

const injectedProjectionMount = ({
  commitModel,
  rollbackError,
  releaseError,
  disposeError,
}: {
  readonly commitModel?: (generation: number) => Promise<void>;
  readonly rollbackError?: Error;
  readonly releaseError?: Error;
  readonly disposeError?: Error;
}) => {
  let replacement = 0;
  const render = vi.fn<PreparedPresentationHandle["render"]>();
  const updateControlBindings = vi.fn<PreparedPresentationHandle["updateControlBindings"]>();
  const rollback = vi.fn<(generation: number) => Promise<void>>(async (generation) => {
    if (generation > 1 && rollbackError !== undefined) {
      throw rollbackError;
    }
  });
  const shellDispose = vi.fn(async () => {
    if (disposeError !== undefined) {
      throw disposeError;
    }
  });
  let currentModels: ReturnType<PreparedPresentationHandle["models"]["snapshot"]> = {
    files: {},
    modelNotifications: [],
  };
  let currentUiValues: ReturnType<PreparedPresentationHandle["uiValues"]["snapshot"]> = {};
  const replaceModels = vi.fn<PreparedPresentationHandle["models"]["replace"]>(
    async (resources) => {
      replacement += 1;
      const generation = replacement;
      return {
        mutated: false,
        remount: false,
        async commit() {
          await commitModel?.(generation);
          currentModels = structuredClone(resources);
        },
        async rollback() {
          await rollback(generation);
        },
      };
    },
  );
  const shell: PreparedPresentationHandle = {
    models: {
      abortSetup() {},
      activate() {},
      snapshot: () => structuredClone(currentModels),
      replace: replaceModels,
      async dispose() {},
    },
    uiValues: {
      snapshot: () => structuredClone(currentUiValues),
      stage: (values) => ({
        commit() {
          currentUiValues = structuredClone(values);
        },
        rollback() {},
      }),
      dispose() {},
    },
    render,
    updateControlBindings,
    update() {},
    dispose: shellDispose,
  };
  const release = vi.fn<PreparedProjectionDependencies["releaseOutputResources"]>((owner, ids) => {
    releaseMarimoOutputResources(owner, ids);
    if (releaseError !== undefined) {
      throw releaseError;
    }
  });
  const mount = createPreparedProjectionMount({
    mountPresentation: () => shell,
    releaseOutputResources: release,
  });
  return {
    mount,
    release,
    render,
    replaceModels,
    rollback,
    shellDispose,
    updateControlBindings,
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
});

test("prepared projections render values, native outputs, and a complete cell", async () => {
  commitRuntimeConfig(config);
  document.body.innerHTML = `
    <div id="runtime"></div>
    <span id="value" data-marimo-studio-site="value-report" mo-value="report"></span>
    <marimo-output value="report.output" aria-label="Report projection"></marimo-output>
    <marimo-output value="report.bundle"></marimo-output>
    <marimo-output value="report.failure"></marimo-output>
    <marimo-cell name="summary" aria-label="Summary projection"></marimo-cell>
  `;
  projectionHosts.connect();
  const controls: Array<{ objectId: string; value: unknown }> = [];
  const handle = mountPreparedProjections({
    root: document.querySelector<HTMLElement>("#runtime")!,
    presentation,
    theme,
    onControlInput: (input) => controls.push(input),
  });
  handles.push(handle);

  await handle.replace(snapshot("one"));
  await settle();

  const value = document.querySelector<MarimoValueHost>("#value")!;
  assert.deepEqual(value.marimoValue, { label: "one", total: 42 });
  assert.equal(value.dataset.state, "ready");
  assert.match(document.body.textContent ?? "", /output one/u);
  assert.equal(
    document
      .querySelector('marimo-output[value="report.output"] > [data-marimo-cell-output]')
      ?.getAttribute("aria-label"),
    "Report projection",
  );
  assert.equal(
    document.querySelector('marimo-output[value="report.output"]')?.getAttribute("role"),
    "group",
  );
  const bundle = document.querySelector<HTMLElement>('marimo-output[value="report.bundle"]')!;
  assert.equal(bundle.dataset.outputMime, "application/vnd.marimo+mimebundle");
  assert.ok(bundle.textContent);
  assert.match(document.body.textContent ?? "", /failure one/u);
  assert.match(document.body.textContent ?? "", /console one/u);
  assert.match(document.body.textContent ?? "", /cell one/u);
  const preparedCell = document.querySelector<HTMLElement>('marimo-cell[name="summary"]')!;
  assert.equal(
    preparedCell
      .querySelector("[data-marimo-presentation='projected-cell']")
      ?.getAttribute("aria-label"),
    "Summary projection",
  );
  assert.equal(preparedCell.querySelector("[contenteditable='true']"), null);
  assert.equal(
    preparedCell.querySelector("[data-testid='console-output-area']")?.getAttribute("tabindex"),
    null,
  );
  document.querySelectorAll("marimo-output, marimo-cell").forEach((host) => {
    assert.ok(host instanceof HTMLElement);
    assert.equal(host.dataset.state, "ready");
  });

  const wrapper = document.createElement("marimo-ui-element");
  wrapper.setAttribute("object-id", "prepared-control");
  const input = document.createElement("button");
  wrapper.append(input);
  document.body.append(wrapper);
  input.dispatchEvent(
    new CustomEvent("marimo-value-input", {
      bubbles: true,
      composed: true,
      detail: { element: input, value: "west" },
    }),
  );
  assert.deepEqual(controls, [{ objectId: "prepared-control", value: "west" }]);

  await Promise.all([handle.dispose(), handle.dispose()]);
});

test("prepared generations replace hosts and retain the last good result", async () => {
  commitRuntimeConfig(config);
  document.body.innerHTML = `
    <div id="runtime"></div>
    <span id="value" data-marimo-studio-site="value-report" mo-value="report"></span>
    <marimo-output value="report.output"></marimo-output>
    <marimo-cell name="summary"></marimo-cell>
  `;
  projectionHosts.connect();
  const handle = mountPreparedProjections({
    root: document.querySelector<HTMLElement>("#runtime")!,
    presentation,
    theme,
  });
  handles.push(handle);
  await handle.replace(snapshot("one"));

  const oldHost = document.querySelector("marimo-output")!;
  const replacement = document.createElement("marimo-output");
  replacement.setAttribute("value", "report.output");
  oldHost.replaceWith(replacement);
  await settle();
  assert.match(replacement.textContent ?? "", /output one/u);

  const invalid = structuredClone(snapshot("invalid"));
  Object.assign(invalid.outputs[0]!.output!, {
    mimetype: "application/vnd.example.unsupported",
  });
  await assert.rejects(handle.replace(invalid));
  assert.match(replacement.textContent ?? "", /output one/u);
  assert.equal(replacement.dataset.state, "error");

  const aborted = new AbortController();
  aborted.abort(new DOMException("superseded", "AbortError"));
  await assert.rejects(handle.replace(snapshot("aborted"), { signal: aborted.signal }));
  assert.match(replacement.textContent ?? "", /output one/u);

  await handle.replace(snapshot("two"));
  await settle();
  assert.match(replacement.textContent ?? "", /output two/u);
  assert.doesNotMatch(replacement.textContent ?? "", /output one/u);
  assert.equal(replacement.dataset.state, "ready");

  await handle.dispose();
});

test("prepared model commit is the supersession linearization point", async () => {
  commitRuntimeConfig(config);
  document.body.innerHTML = `
    <div id="runtime"></div>
    <span id="value" data-marimo-studio-site="value-report" mo-value="report"></span>
  `;
  projectionHosts.connect();
  let releaseCommit = () => {};
  const commitGate = new Promise<void>((resolve) => {
    releaseCommit = resolve;
  });
  let commitStarted = () => {};
  const started = new Promise<void>((resolve) => {
    commitStarted = resolve;
  });
  const failure = new Error("newer model commit failed");
  const injected = injectedProjectionMount({
    commitModel: async (generation) => {
      if (generation === 2) {
        commitStarted();
        await commitGate;
      }
      if (generation === 3) {
        throw failure;
      }
    },
  });
  const handle = injected.mount({
    root: document.querySelector<HTMLElement>("#runtime")!,
    presentation,
    theme,
  });
  handles.push(handle);
  await handle.replace(snapshot("baseline"));

  const committed = handle.replace(snapshot("committed"));
  await started;
  const failed = handle.replace(snapshot("failed"));
  releaseCommit();

  await committed;
  await assert.rejects(failed, failure);
  const value = document.querySelector<MarimoValueHost>("#value")!;
  assert.deepEqual(value.marimoValue, { label: "committed", total: 42 });
});

test("failed model commit releases resources introduced by the rejected snapshot", async () => {
  commitRuntimeConfig(config);
  document.body.innerHTML = `
    <div id="runtime"></div>
    <span id="value" data-marimo-studio-site="value-report" mo-value="report"></span>
  `;
  projectionHosts.connect();
  const failure = new Error("model commit failed");
  const injected = injectedProjectionMount({
    commitModel: async (generation) => {
      if (generation === 2) {
        throw failure;
      }
    },
  });
  const handle = injected.mount({
    root: document.querySelector<HTMLElement>("#runtime")!,
    presentation,
    theme,
  });
  handles.push(handle);
  await handle.replace(snapshot("baseline"));

  const rejectedBase = snapshot("rejected");
  const ownerCellId = "rejected-unhosted-owner";
  const projectionSha256 = "b".repeat(64);
  const objectId = `${ownerCellId}-projection-${projectionSha256}-ui-0`;
  const rejected: PreparedProjectionSnapshot = {
    ...rejectedBase,
    outputs: [
      ...rejectedBase.outputs,
      {
        schema: "marimo.output.v1",
        selector: "unhosted.output",
        ownerCellId,
        projectionSha256,
        output: { channel: "output", mimetype: "text/plain", data: "unhosted" },
        resources: {
          files: {},
          functions: { [objectId]: [] },
          modelNotifications: [],
          uiValues: { [objectId]: "staged" },
        },
      },
    ],
  };

  await assert.rejects(handle.replace(rejected), failure);

  assert.deepEqual(injected.release.mock.calls, [[ownerCellId, [objectId]]]);
});

test("prepared function and stdin resources fail through the capability boundary", async () => {
  commitRuntimeConfig(config);
  document.body.innerHTML = `
    <div id="runtime"></div>
    <marimo-output value="report.output"></marimo-output>
    <marimo-cell name="summary"></marimo-cell>
  `;
  projectionHosts.connect();
  const handle = mountPreparedProjections({
    root: document.querySelector<HTMLElement>("#runtime")!,
    presentation,
    theme,
  });
  handles.push(handle);

  const functions = structuredClone(snapshot("functions"));
  Object.assign(functions.outputs[0]!.resources, {
    functions: { control: ["on_change"] },
  });
  await assert.rejects(handle.replace(functions), /must be empty for static replay/u);

  const stdin = structuredClone(snapshot("stdin"));
  Object.assign(stdin.cells[0]!, {
    console: [{ channel: "stdin", mimetype: "text/plain", data: "Name?" }],
  });
  await assert.rejects(
    handle.replace(stdin),
    (error) =>
      error instanceof PreparedProjectionCapabilityError &&
      error.code === "prepared-stdin-unsupported",
  );

  await handle.dispose();
});

test("prepared UI values mount before controls and clear across a null generation", async () => {
  commitRuntimeConfig(config);
  document.body.innerHTML = `
    <div id="runtime"></div>
    <marimo-output value="report.output"></marimo-output>
  `;
  projectionHosts.connect();
  const controlEvents: Array<{ objectId: string; value: unknown }> = [];
  const handle = mountPreparedProjections({
    root: document.querySelector<HTMLElement>("#runtime")!,
    presentation,
    theme,
    onControlInput: (input) => controlEvents.push(input),
  });
  handles.push(handle);
  const objectId = projectionUiId("prepared-report-output", "d", "control");
  const state = (value: number): PreparedProjectionSnapshot => {
    const interactive = structuredClone(snapshot(`state-${value}`));
    Object.assign(interactive.outputs[0]!, {
      output: {
        channel: "output",
        mimetype: "text/html",
        data: `<marimo-ui-element object-id="${objectId}"><marimo-slider data-initial-value="2" data-label="null" data-start="0" data-stop="10" data-steps="null"></marimo-slider></marimo-ui-element>`,
      },
      resources: {
        files: {},
        modelNotifications: [],
        functions: { [objectId]: [] },
        uiValues: { [objectId]: value },
      },
    });
    return interactive;
  };
  await handle.replace(state(2));
  const host = document.querySelector<HTMLElement>("marimo-output")!;
  const sliderValue = (expected: string): Promise<void> =>
    vi.waitFor(() => {
      const slider = host.querySelector("marimo-slider");
      const rendered = slider?.shadowRoot?.querySelector('[role="slider"]');
      assert.equal(rendered?.getAttribute("aria-valuenow"), expected);
    });
  await sliderValue("2");

  await handle.replace(state(3));
  await sliderValue("3");
  const renderedSlider = host.querySelector<HTMLElement>("marimo-slider")!;
  renderedSlider.dispatchEvent(
    new CustomEvent("marimo-value-update", {
      detail: { element: renderedSlider, value: 4 },
    }),
  );
  await sliderValue("4");
  await handle.restore();
  await sliderValue("3");
  assert.equal(host.querySelector("marimo-slider"), renderedSlider);

  const broken = structuredClone(state(5));
  Object.assign(broken.outputs[0]!.output!, {
    mimetype: "application/vnd.example.unsupported",
  });
  await assert.rejects(handle.replace(broken));
  await sliderValue("3");
  await handle.replace(state(2));
  await sliderValue("2");
  assert.equal(host.querySelector("marimo-slider"), renderedSlider);
  await handle.replace(state(3));
  await sliderValue("3");
  renderedSlider.dispatchEvent(
    new CustomEvent("marimo-value-input", {
      bubbles: true,
      composed: true,
      detail: { element: renderedSlider, value: 4 },
    }),
  );
  assert.deepEqual(controlEvents.at(-1), { objectId, value: 4 });

  const empty = structuredClone(snapshot("empty"));
  Object.assign(empty.outputs[0]!, {
    output: null,
    resources: resources(),
  });
  await handle.replace(empty);
  assert.equal(host.querySelector(`[object-id="${objectId}"]`), null);
  assert.equal(host.dataset.state, "ready");
});

test("same-owner null cells preserve a surviving UI output across states", async () => {
  commitRuntimeConfig(config);
  document.body.innerHTML = `
    <div id="runtime"></div>
    <marimo-output value="shared.output"></marimo-output>
    <marimo-cell name="shared"></marimo-cell>
  `;
  projectionHosts.connect();
  const handle = mountPreparedProjections({
    root: document.querySelector<HTMLElement>("#runtime")!,
    presentation,
    theme,
  });
  handles.push(handle);
  const ownerCellId = "shared-owner-cell";
  const objectId = projectionUiId(ownerCellId, "8", "shared-control");
  const state = (value: number | null): PreparedProjectionSnapshot => ({
    values: [],
    outputs: [
      {
        schema: "marimo.output.v1",
        selector: "shared.output",
        ownerCellId,
        projectionSha256: "8".repeat(64),
        output:
          value === null
            ? null
            : {
                channel: "output",
                mimetype: "text/html",
                data: `<marimo-ui-element object-id="${objectId}"><marimo-slider data-initial-value="2" data-label="null" data-start="0" data-stop="10" data-steps="null"></marimo-slider></marimo-ui-element>`,
              },
        resources:
          value === null
            ? resources()
            : {
                files: {},
                modelNotifications: [],
                functions: { [objectId]: [] },
                uiValues: { [objectId]: value },
              },
      },
    ],
    cells: [
      {
        schema: "marimo.cell.v1",
        alias: "shared",
        projectionSha256: "9".repeat(64),
        cell: {
          id: ownerCellId,
          name: "shared",
          codeSha256: "8".repeat(64),
          config: {},
        },
        outcome: "completed",
        console: [],
        output: null,
        resources: resources(),
      },
    ],
  });
  const host = document.querySelector<HTMLElement>('marimo-output[value="shared.output"]')!;
  const sliderValue = (expected: string): Promise<HTMLElement> =>
    vi.waitFor(() => {
      const slider = host.querySelector<HTMLElement>("marimo-slider");
      assert.ok(slider);
      assert.equal(
        slider.shadowRoot?.querySelector('[role="slider"]')?.getAttribute("aria-valuenow"),
        expected,
      );
      return slider;
    });

  await handle.replace(state(2));
  const slider = await sliderValue("2");
  await handle.replace(state(3));
  assert.equal(await sliderValue("3"), slider);
  await handle.replace(state(4));
  assert.equal(await sliderValue("4"), slider);

  await handle.replace(state(null));
  assert.equal(host.querySelector("marimo-slider"), null);
  await handle.dispose();
});

test("prepared UI values reject conflicts across projections", async () => {
  commitRuntimeConfig(config);
  document.body.innerHTML = `
    <div id="runtime"></div>
    <marimo-output value="report.output"></marimo-output>
  `;
  projectionHosts.connect();
  const handle = mountPreparedProjections({
    root: document.querySelector<HTMLElement>("#runtime")!,
    presentation,
    theme,
  });
  handles.push(handle);
  const ownerCellId = "prepared-report-output";
  const objectId = projectionUiId(ownerCellId, "e", "control");
  const conflicting = structuredClone(snapshot("conflict"));
  Object.assign(conflicting.outputs[0]!, { projectionSha256: "e".repeat(64) });
  Object.assign(conflicting.outputs[0]!.resources, {
    functions: { [objectId]: [] },
    uiValues: { [objectId]: 2 },
  });
  Object.assign(conflicting.outputs[1]!, {
    ownerCellId,
    projectionSha256: "e".repeat(64),
    resources: {
      ...conflicting.outputs[1]!.resources,
      functions: { [objectId]: [] },
      uiValues: { [objectId]: 3 },
    },
  });
  await assert.rejects(handle.replace(conflicting), /conflicting UI values/u);
});

test("prepared UI resources require owner-scoped projection identities", async () => {
  commitRuntimeConfig(config);
  const handle = mountPreparedProjections({
    root: document.createElement("div"),
    presentation,
    theme,
  });
  handles.push(handle);
  const outside = structuredClone(snapshot("outside-owner"));
  const outsideId = `projection-${"e".repeat(64)}-ui-control`;
  Object.assign(outside.outputs[0]!.resources, {
    functions: { [outsideId]: [] },
    uiValues: { [outsideId]: 2 },
  });
  await assert.rejects(handle.replace(outside), /projection-scoped/u);

  const mismatched = structuredClone(snapshot("mismatched-resources"));
  const objectId = projectionUiId("prepared-report-output", "d", "control");
  Object.assign(mismatched.outputs[0]!.resources, {
    functions: { [objectId]: [] },
    uiValues: {},
  });
  await assert.rejects(handle.replace(mismatched), /replay UI value/u);
});

test("prepared resources deduplicate shared models and reject conflicts", async () => {
  commitRuntimeConfig(config);
  document.body.innerHTML = `
    <div id="runtime"></div>
    <marimo-output value="report.output"></marimo-output>
    <marimo-output value="report.bundle"></marimo-output>
  `;
  projectionHosts.connect();
  const handle = mountPreparedProjections({
    root: document.querySelector<HTMLElement>("#runtime")!,
    presentation,
    theme,
  });
  handles.push(handle);
  const shared = {
    files: { "widget.js": "data:text/javascript,export default {}" },
    modelNotifications: [
      {
        op: "model-lifecycle" as const,
        model_id: `projection-${"d".repeat(64)}-model-0`,
        message: { method: "close" as const },
      },
    ],
    functions: {},
    uiValues: {},
  };
  const duplicated = structuredClone(snapshot("shared"));
  Object.assign(duplicated.outputs[0]!, { resources: shared });
  Object.assign(duplicated.outputs[1]!, {
    projectionSha256: "d".repeat(64),
    resources: shared,
  });
  await handle.replace(duplicated);

  const conflicting = structuredClone(duplicated);
  Object.assign(conflicting.outputs[1]!, {
    resources: {
      ...shared,
      modelNotifications: [
        {
          op: "model-lifecycle",
          model_id: `projection-${"d".repeat(64)}-model-0`,
          message: { method: "custom", content: {}, buffers: [] },
        },
      ],
    },
  });
  await assert.rejects(handle.replace(conflicting), /conflicting lifecycle records/u);
});

test("prepared model files preserve reserved resource names", async () => {
  const injected = injectedProjectionMount({});
  const handle = injected.mount({
    root: document.createElement("div"),
    presentation,
    theme,
  });
  handles.push(handle);
  const reserved = snapshot("reserved-files");
  Object.assign(reserved.outputs[0]!, {
    resources: {
      ...reserved.outputs[0]!.resources,
      files: Object.fromEntries([
        ["__proto__", "data:text/plain;base64,cHJvdG8="],
        ["constructor", "data:text/plain;base64,Y29uc3RydWN0b3I="],
        ["toString", "data:text/plain;base64,dG9TdHJpbmc="],
      ]),
    },
  });

  await handle.replace(reserved);

  const modelResources = injected.replaceModels.mock.calls[0]?.[0];
  assert.ok(modelResources);
  assert.equal(Object.hasOwn(modelResources.files, "__proto__"), true);
  assert.equal(modelResources.files.__proto__, "data:text/plain;base64,cHJvdG8=");
  assert.equal(modelResources.files.constructor, "data:text/plain;base64,Y29uc3RydWN0b3I=");
  assert.equal(modelResources.files.toString, "data:text/plain;base64,dG9TdHJpbmc=");
});

test("prepared replacement attempts restore after model rollback fails", async () => {
  const rollbackError = new Error("model rollback failed");
  const injected = injectedProjectionMount({ rollbackError });
  const handle = injected.mount({
    root: document.createElement("div"),
    presentation,
    theme,
  });
  handles.push(handle);
  await handle.replace({ values: [], outputs: [], cells: [] });
  const invalid: PreparedProjectionSnapshot = {
    values: [],
    outputs: [
      {
        schema: "marimo.output.v1",
        selector: "invalid.output",
        ownerCellId: "injected-invalid-owner",
        projectionSha256: "1".repeat(64),
        output: {
          channel: "output",
          mimetype: "application/vnd.example.unsupported",
          data: "invalid",
        },
        resources: resources(),
      },
    ],
    cells: [],
  };

  await assert.rejects(
    handle.replace(invalid),
    (error) => error instanceof AggregateError && error.errors.includes(rollbackError),
  );
  assert.equal(injected.rollback.mock.calls.length, 1);
  assert.equal(injected.render.mock.calls.length, 2);
});

test("prepared checkpoints restore the committed projection and controls", async () => {
  const injected = injectedProjectionMount({});
  const handle = injected.mount({
    root: document.createElement("div"),
    presentation,
    theme,
  });
  handles.push(handle);
  const firstBindings = {
    "first-control": { input: "filters", path: [{ kind: "key" as const, value: "region" }] },
  };
  const secondBindings = {
    "second-control": { input: "scale", path: [] },
  };
  await handle.replace(snapshot("checkpoint-one"));
  handle.updateControlBindings(firstBindings);
  const checkpoint = handle.checkpoint();

  await handle.replace(snapshot("checkpoint-two"));
  handle.updateControlBindings(secondBindings);
  const restoration = checkpoint.restore();
  assert.equal(checkpoint.restore(), restoration);
  await restoration;

  const rendered = injected.render.mock.lastCall?.[0];
  assert.ok(isValidElement<{ snapshot: PreparedProjectionSnapshot }>(rendered));
  assert.deepEqual(rendered.props.snapshot.values[0]?.value, {
    codec: "json-v1",
    fingerprint: `sha256:${"a".repeat(64)}`,
    value: { label: "checkpoint-one", total: 42 },
  });
  assert.deepEqual(injected.updateControlBindings.mock.lastCall?.[0], firstBindings);

  checkpoint.dispose();
  const calls = injected.render.mock.calls.length;
  await checkpoint.restore();
  assert.equal(injected.render.mock.calls.length, calls);
});

test("prepared disposal attempts shell cleanup after owner release fails", async () => {
  const releaseError = new Error("owner release failed");
  const disposeError = new Error("prepared shell disposal failed");
  const injected = injectedProjectionMount({ releaseError, disposeError });
  const objectId = projectionUiId("injected-ready-owner", "f", "control");
  const handle = injected.mount({
    root: document.createElement("div"),
    presentation,
    theme,
  });
  await handle.replace({
    values: [],
    outputs: [
      {
        schema: "marimo.output.v1",
        selector: "ready.output",
        ownerCellId: "injected-ready-owner",
        projectionSha256: "f".repeat(64),
        output: { channel: "output", mimetype: "text/plain", data: "ready" },
        resources: {
          ...resources(),
          functions: { [objectId]: [] },
          uiValues: { [objectId]: 1 },
        },
      },
    ],
    cells: [],
  });

  await assert.rejects(
    handle.dispose(),
    (error) =>
      error instanceof AggregateError &&
      error.errors.includes(releaseError) &&
      error.errors.includes(disposeError),
  );
  assert.equal(injected.release.mock.calls.length, 1);
  assert.equal(injected.shellDispose.mock.calls.length, 1);
});
