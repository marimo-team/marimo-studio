import type { EmbeddedRuntimeView } from "@marimo-studio/marimo-frontend/embedded-runtime";
import type { RuntimeContext, RuntimeSession } from "@marimo-studio/runtime";

import { isSessionId } from "@marimo-studio/marimo-frontend/session-bootstrap";
import { isValidElement } from "react";
import { expect, it, vi } from "vite-plus/test";

import type { OutputReader } from "../src/outputs/reader.ts";
import type { RuntimeInvoke, RuntimeMountOptions } from "../src/runtime/runtime.tsx";
import type { WasmRuntimeData } from "../src/runtime/wasm-config.ts";
import type { ValueReader } from "../src/values/reader.ts";

import { wasmRuntime } from "../src/runtime/catalog.ts";
import { mountSharedRuntime } from "../src/runtime/runtime.tsx";
import { mountWasmRuntime } from "../src/runtime/wasm.ts";
import { preparedRuntimeConfig } from "./prepared-fixture.ts";

const sessionId = "s_abc123";
if (!isSessionId(sessionId)) {
  throw new TypeError("Runtime adapter fixture session ID is invalid");
}

const mountReaderRuntime = (valueReader: ValueReader, outputReader: OutputReader) => {
  let readValues: ValueReader | undefined;
  let readOutputs: OutputReader | undefined;
  const runtimeView: EmbeddedRuntimeView = {
    cells: [],
    connection: { state: "OPEN" },
    initialization: { state: "ready" },
    initialized: Promise.resolve(),
    invoke: async () => null,
    sessionId,
    submitStdin: () => {},
  };
  const mount: NonNullable<Parameters<typeof mountSharedRuntime>[3]> = vi.fn((options) => {
    const projections = options.render(runtimeView);
    if (!isValidElement<{ readOutputs: OutputReader; readValues: ValueReader }>(projections)) {
      throw new TypeError("Shared runtime did not render its projection readers");
    }
    ({ readOutputs, readValues } = projections.props);
    return {
      initialized: Promise.resolve(),
      invoke: async () => null,
      sessionId,
      update: vi.fn(),
      dispose: vi.fn(),
    };
  });
  const session = mountSharedRuntime(
    preparedRuntimeConfig,
    document.createElement("div"),
    {
      id: preparedRuntimeConfig.runtime.descriptor.id,
      instance: preparedRuntimeConfig.runtime.instance,
      initialMode: "read",
      viewMode: "read",
      exposeSession: false,
      transport: {
        kind: "server",
        serverToken: "token",
        transformTransportURL: (url) => url,
        url: "https://example.test/",
      },
      valueReader: () => valueReader,
      outputReader: () => outputReader,
    },
    mount,
  );
  if (readValues === undefined || readOutputs === undefined) {
    throw new TypeError("Shared runtime projection readers were not installed");
  }
  return { readOutputs, readValues, session };
};

it("restores the prior shared presentation after a successful update", async () => {
  const updates = vi.fn();
  const mount: NonNullable<Parameters<typeof mountSharedRuntime>[3]> = vi.fn(() => ({
    initialized: Promise.resolve(),
    invoke: async () => null,
    sessionId,
    update: updates,
    dispose: vi.fn(),
  }));
  const options: RuntimeMountOptions = {
    id: preparedRuntimeConfig.runtime.descriptor.id,
    instance: preparedRuntimeConfig.runtime.instance,
    initialMode: "read",
    viewMode: "read",
    exposeSession: false,
    transport: {
      kind: "server",
      serverToken: "token",
      transformTransportURL: (url) => url,
      url: "https://example.test/",
    },
    valueReader: () => async () => ({ values: {}, errors: {} }),
    outputReader: () => async () => ({ outputs: {}, errors: {} }),
  };
  const session = mountSharedRuntime(
    preparedRuntimeConfig,
    document.createElement("div"),
    options,
    mount,
  );
  const revision = await session.beginRevision(new AbortController().signal);
  const next = {
    ...preparedRuntimeConfig,
    appConfig: { revision: "B" },
  };

  await revision.apply(next);
  await revision.rollback();

  expect(updates).toHaveBeenNthCalledWith(1, {
    appConfig: { revision: "B" },
    configOverrides: {},
    userConfig: {},
  });
  expect(updates).toHaveBeenNthCalledWith(2, {
    appConfig: {},
    configOverrides: {},
    userConfig: {},
  });
});

it("cancels value reads before a revision and admits the committed revision", async () => {
  const sourceReader = vi.fn<ValueReader>(async (request, signal) => {
    if (request.revision !== "revision-b") {
      return await new Promise((_resolve, reject) => {
        const abort = () => reject(signal?.reason);
        signal?.addEventListener("abort", abort, { once: true });
      });
    }
    return { values: { report: "B" }, errors: {} };
  });
  const { readValues, session } = mountReaderRuntime(sourceReader, async () => ({
    outputs: {},
    errors: {},
  }));

  const first = readValues({ revision: preparedRuntimeConfig.revision, selectors: ["report"] });
  await vi.waitFor(() => expect(sourceReader).toHaveBeenCalledOnce());
  const revision = await session.beginRevision(new AbortController().signal);
  const firstFailure = expect(first).rejects.toMatchObject({ name: "AbortError" });
  const next = { ...preparedRuntimeConfig, revision: "revision-b" };
  const second = readValues({ revision: next.revision, selectors: ["report"] });

  await revision.apply(next);
  await Promise.resolve();
  expect(sourceReader).toHaveBeenCalledOnce();
  await revision.commit();

  await firstFailure;
  await expect(second).resolves.toEqual({ values: { report: "B" }, errors: {} });
  expect(sourceReader).toHaveBeenCalledTimes(2);
});

it("cancels output reads before a revision and restores admission after rollback", async () => {
  let initialRead = true;
  const sourceReader = vi.fn<OutputReader>(async (_request, signal) => {
    if (initialRead) {
      initialRead = false;
      return await new Promise((_resolve, reject) => {
        const abort = () => reject(signal?.reason);
        signal?.addEventListener("abort", abort, { once: true });
      });
    }
    return { outputs: {}, errors: {} };
  });
  const { readOutputs, session } = mountReaderRuntime(
    async () => ({ values: {}, errors: {} }),
    sourceReader,
  );
  const request = {
    revision: preparedRuntimeConfig.revision,
    selectors: ["report"],
    activeSelectors: ["report"],
  };
  const first = readOutputs(request);
  await vi.waitFor(() => expect(sourceReader).toHaveBeenCalledOnce());
  const revision = await session.beginRevision(new AbortController().signal);
  const next = { ...preparedRuntimeConfig, revision: "revision-b" };
  const stale = readOutputs({ ...request, revision: next.revision });
  const staleFailure = expect(stale).rejects.toMatchObject({ name: "AbortError" });

  await revision.apply(next);
  await Promise.resolve();
  expect(sourceReader).toHaveBeenCalledOnce();
  await revision.rollback();

  await staleFailure;
  await expect(first).resolves.toEqual({ outputs: {}, errors: {} });
  expect(sourceReader).toHaveBeenCalledTimes(2);
});

it("validates WebAssembly data before mutation and restores prior projection specs", async () => {
  const initialData: WasmRuntimeData = {
    code: "print('A')",
    filename: "notebook.py",
    version: "0.24.0",
    valueSpecs: {},
    outputSpecs: {},
  };
  const nextData: WasmRuntimeData = {
    ...initialData,
    code: "print('B')",
    valueSpecs: { metric: ["context", [["attribute", "label"]]] },
  };
  const config = (data: RuntimeContext["presentation"]["runtime"]["data"]) => ({
    ...preparedRuntimeConfig,
    runtime: {
      descriptor: wasmRuntime.descriptor,
      instance: "wasm-instance",
      data,
    },
  });
  const sharedApply = vi.fn(async () => "applied" as const);
  const sharedRollback = vi.fn(async () => {});
  const sharedRevision = {
    apply: sharedApply,
    commit: vi.fn(async () => {}),
    rollback: sharedRollback,
  };
  const shared: RuntimeSession = {
    id: "wasm",
    updateQuery: vi.fn(async () => {}),
    beginRevision: vi.fn(async () => sharedRevision),
    dispose: vi.fn(),
  };
  let options: RuntimeMountOptions | undefined;
  const mountRuntime: NonNullable<Parameters<typeof mountWasmRuntime>[2]> = vi.fn(
    (_presentation, _root, mountedOptions) => {
      options = mountedOptions;
      return shared;
    },
  );
  const context: RuntimeContext = {
    presentation: config(initialData),
    root: document.createElement("div"),
    signal: new AbortController().signal,
    commitRuntimeInstance: vi.fn(),
  };
  const session = mountWasmRuntime(context, initialData, mountRuntime);
  const revision = await session.beginRevision(new AbortController().signal);

  await expect(revision.apply(config({ ...nextData, valueSpecs: null }))).rejects.toThrow();
  expect(sharedApply).not.toHaveBeenCalled();

  await revision.apply(config(nextData));
  const invoke = vi.fn<RuntimeInvoke>(async (request) =>
    request.functionName === "read_values"
      ? {
          found: true,
          status: { code: "ok", message: null },
          return_value: { values: {}, errors: {} },
        }
      : { found: true, status: { code: "ok", message: null }, return_value: null },
  );
  const reader = options?.valueReader({
    initialized: Promise.resolve(),
    invoke,
    sessionId,
  });
  if (reader === undefined) {
    throw new TypeError("WebAssembly value reader was not configured");
  }
  await reader({ revision: "B", selectors: [] });
  await revision.rollback();

  const projectionRequests = invoke.mock.calls
    .map(([request]) => request)
    .filter((request) => request.functionName === "sync_projection_specs");
  expect(projectionRequests.map((request) => request.args.value_specs)).toEqual([
    nextData.valueSpecs,
    initialData.valueSpecs,
  ]);
  expect(sharedRollback).toHaveBeenCalledOnce();
});
