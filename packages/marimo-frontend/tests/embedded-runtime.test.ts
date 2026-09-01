// @vitest-environment jsdom

import { CellId } from "@marimo-team/frontend/unstable_internal/core/cells/ids";
import {
  createCell,
  createCellRuntimeState,
} from "@marimo-team/frontend/unstable_internal/core/cells/types";
import { act, createElement, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, expect, test, vi } from "vite-plus/test";

import type {
  EmbeddedRuntimeHost,
  EmbeddedRuntimeRenderer,
  EmbeddedTransportHost,
} from "../src/embedded-runtime-core.ts";
import type {
  EmbeddedCellActions,
  EmbeddedRequestClient,
  EmbeddedRuntimeKernel,
} from "../src/embedded-runtime-view.tsx";
import type {
  EmbeddedConnection,
  EmbeddedFunction,
  EmbeddedFunctionResult,
  EmbeddedPresentationConfig,
  EmbeddedRuntimeHandle,
  EmbeddedRuntimeCell,
  EmbeddedRuntimeView,
  EmbeddedServerTransport,
  EmbeddedThemeSource,
  EmbeddedWasmTransport,
} from "../src/embedded-runtime.tsx";
import type { SessionId } from "../src/session-bootstrap.ts";

import { parseEmbeddedJsonValue } from "../src/embedded-json.ts";
import {
  bindModelValueSenderToPage,
  createEmbeddedRuntimeMount,
  createTransportInitializer,
} from "../src/embedded-runtime-core.ts";
import { EmbeddedRuntimeViewComponent } from "../src/embedded-runtime-view.tsx";
import { mountEmbeddedRuntime as mountMarimoRuntime } from "../src/embedded-runtime.tsx";
import { bootstrapSession, isSessionId } from "../src/session-bootstrap.ts";
import { getRuntimeManager } from "../src/upstream/runtime.ts";

const testSessionId = (): SessionId => {
  const sessionId = "s_abc123";
  if (!isSessionId(sessionId)) {
    throw new Error("The test session identifier must follow Marimo's session format");
  }
  return sessionId;
};

const functionResult: EmbeddedFunctionResult = {
  found: true,
  return_value: { found: true },
  status: { code: "ok", message: null, title: "Success" },
};

class RuntimeManagerDouble {
  headers = () => ({ "Marimo-Session-Id": "s_native" });

  sessionHeaders = () => ({ "Marimo-Session-Id": "s_native" });

  getWsURL = (_sessionId: SessionId): URL => new URL("ws://example.test/ws?session_id=s_abc123");

  getSseURL = (_sessionId: SessionId): URL =>
    new URL("https://example.test/sse?session_id=s_abc123");
}

class TransportHostDouble implements EmbeddedTransportHost {
  readonly runtime = new RuntimeManagerDouble();
  readonly serverTransports = new Array<EmbeddedServerTransport>();
  readonly wasmTransports = new Array<EmbeddedWasmTransport>();
  readonly workerInitialized = Promise.resolve();
  serverRequestActivations = 0;
  serverRequestReleases = 0;
  wasmReleases = 0;
  readonly executeWasmCells = vi.fn(async () => {});

  activateServerRequests(): () => void {
    this.serverRequestActivations += 1;
    let active = true;
    return () => {
      if (!active) {
        return;
      }
      active = false;
      this.serverRequestReleases += 1;
    };
  }

  prepareServer(transport: EmbeddedServerTransport): RuntimeManagerDouble {
    this.serverTransports.push(transport);
    return this.runtime;
  }

  prepareWasm(transport: EmbeddedWasmTransport): Promise<void> {
    this.wasmTransports.push(transport);
    return this.workerInitialized;
  }

  releaseWasm(): void {
    this.wasmReleases += 1;
  }
}

type MountRender = (runtime: EmbeddedRuntimeView) => ReactNode;

class RuntimeRendererDouble implements EmbeddedRuntimeRenderer {
  readonly root: Root;
  disposeCalls = 0;

  constructor(
    element: HTMLElement,
    private readonly host: RuntimeHostDouble,
  ) {
    this.root = createRoot(element);
  }

  render(initialized: Promise<void>, renderView: MountRender, sessionId: SessionId): void {
    if (this.host.renderError) {
      throw this.host.renderError;
    }
    const connection: EmbeddedConnection = { state: "OPEN" };
    const view: EmbeddedRuntimeView = {
      cells: [],
      connection,
      initialization: { state: "ready" },
      initialized,
      invoke: this.host.invoke,
      sessionId,
      submitStdin: () => {},
    };
    this.host.view = view;
    this.root.render(renderView(view));
  }

  dispose(): void {
    this.disposeCalls += 1;
    this.root.unmount();
  }
}

interface PresentationCall {
  readonly config: EmbeddedPresentationConfig;
  readonly initialMode: "edit" | "read";
  readonly theme: "light" | "dark" | undefined;
  readonly viewMode: "present" | "read";
}

interface ThemeCall {
  readonly config: EmbeddedPresentationConfig;
  readonly theme: "light" | "dark" | undefined;
}

class RuntimeHostDouble implements EmbeddedRuntimeHost {
  readonly transport = new TransportHostDouble();
  readonly presentationCalls = new Array<PresentationCall>();
  readonly themeCalls = new Array<ThemeCall>();
  readonly invoke: EmbeddedFunction = vi.fn(async () => functionResult);
  readonly initializeTransport = createTransportInitializer(this.transport, this.invoke);
  connectingCalls = 0;
  initializeCalls = 0;
  renderError: Error | undefined;
  renderer: RuntimeRendererDouble | undefined;
  view: EmbeddedRuntimeView | undefined;

  configurePresentation(
    config: EmbeddedPresentationConfig,
    initialMode: "edit" | "read",
    viewMode: "present" | "read",
    theme: "light" | "dark" | undefined,
  ): void {
    this.presentationCalls.push({ config, initialMode, theme, viewMode });
  }

  configureTheme(config: EmbeddedPresentationConfig, theme: "light" | "dark" | undefined): void {
    this.themeCalls.push({ config, theme });
  }

  createRenderer(element: HTMLElement): RuntimeRendererDouble {
    const renderer = new RuntimeRendererDouble(element, this);
    this.renderer = renderer;
    return renderer;
  }

  currentSessionId(): SessionId {
    return testSessionId();
  }

  initialize(): void {
    this.initializeCalls += 1;
  }

  setConnecting(): void {
    this.connectingCalls += 1;
  }
}

type KernelNotebook = readonly EmbeddedRuntimeCell[];

class KernelDouble implements EmbeddedRuntimeKernel<KernelNotebook> {
  readonly invoke: EmbeddedFunction = vi.fn(async () => functionResult);
  readonly setCells: EmbeddedCellActions["setCells"] = vi.fn();
  readonly setStdinResponse: EmbeddedCellActions["setStdinResponse"] = vi.fn();
  readonly sendComponentValues: EmbeddedRequestClient["sendComponentValues"] = vi.fn(
    async () => null,
  );
  readonly sendStdin: EmbeddedRequestClient["sendStdin"] = vi.fn(async () => null);
  readonly connectionAutoInstantiate = new Array<boolean>();
  readonly connectionSessions = new Array<SessionId>();
  startCalls = 0;
  stopCalls = 0;

  constructor(private readonly notebook: KernelNotebook) {}

  flattenCells(notebook: KernelNotebook): EmbeddedRuntimeCell[] {
    return [...notebook];
  }

  startRuntime(_sendComponentValues: EmbeddedRequestClient["sendComponentValues"]): void {
    this.startCalls += 1;
  }

  stopRuntime(): void {
    this.stopCalls += 1;
  }

  useCellActions(): EmbeddedCellActions {
    return {
      setCells: this.setCells,
      setStdinResponse: this.setStdinResponse,
    };
  }

  useConnection(
    input: Parameters<EmbeddedRuntimeKernel<KernelNotebook>["useConnection"]>[0],
  ): EmbeddedConnection {
    this.connectionAutoInstantiate.push(input.autoInstantiate);
    this.connectionSessions.push(input.sessionId);
    return { state: "OPEN" };
  }

  useNotebook(): KernelNotebook {
    return this.notebook;
  }

  useRequestClient(): EmbeddedRequestClient {
    return {
      sendComponentValues: this.sendComponentValues,
      sendStdin: this.sendStdin,
    };
  }
}

const presentation = (theme = "system"): EmbeddedPresentationConfig => ({
  appConfig: { width: "full" },
  configOverrides: { runtime: "embedded" },
  userConfig: { display: { theme } },
});

const createThemeSource = () => {
  let current: "light" | "dark" | undefined = "light";
  const listeners = new Set<() => void>();
  const source: EmbeddedThemeSource = {
    current: () => current,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
  return {
    source,
    emit() {
      for (const listener of listeners) {
        listener();
      }
    },
    listeners,
    set(value: "light" | "dark" | undefined) {
      current = value;
    },
  };
};

const root = (): HTMLElement => {
  const element = document.createElement("div");
  document.body.append(element);
  return element;
};

const serverTransport = (
  transformTransportURL: EmbeddedServerTransport["transformTransportURL"] = (url) => url,
): EmbeddedServerTransport => ({
  kind: "server",
  presentationSessionId: "s_view01",
  serverToken: "token",
  transformTransportURL,
  url: "https://example.test/base/",
});

const wasmTransport = (
  waitForReady: EmbeddedWasmTransport["waitForReady"] = () => undefined,
): EmbeddedWasmTransport => ({
  kind: "wasm",
  autoInstantiate: false,
  code: "print('ready')",
  filename: "notebook.py",
  url: "https://example.test/",
  version: "1.2.3",
  waitForReady,
});

beforeEach(() => {
  document.body.replaceChildren();
  delete globalThis.__MARIMO_STUDIO_SESSION_ID__;
});

test("mounts, updates, and disposes the server runtime through one handle", async () => {
  const target = root();
  const theme = createThemeSource();
  const host = new RuntimeHostDouble();
  const mountEmbeddedRuntime = createEmbeddedRuntimeMount(host);
  const originalGetWsURL = host.transport.runtime.getWsURL;
  const originalGetSseURL = host.transport.runtime.getSseURL;
  globalThis.__MARIMO_STUDIO_SESSION_ID__ = "s_before";
  let handle!: EmbeddedRuntimeHandle;

  await act(async () => {
    handle = mountEmbeddedRuntime({
      autoInstantiate: true,
      exposeSession: true,
      initialMode: "read",
      presentation: presentation(),
      render(runtime) {
        return createElement("div", { "data-runtime-view": "" }, runtime.sessionId);
      },
      root: target,
      theme: theme.source,
      transport: serverTransport((url) => {
        url.searchParams.set("embedded", "true");
        return url;
      }),
      viewMode: "read",
    });
    await handle.initialized;
  });

  expect(handle.sessionId).toBe("s_abc123");
  expect(globalThis.__MARIMO_STUDIO_SESSION_ID__).toBe("s_abc123");
  expect(host.view?.cells).toEqual([]);
  expect(host.view?.connection.state).toBe("OPEN");
  expect(host.view?.initialization).toEqual({ state: "ready" });
  expect(target.textContent).toBe("s_abc123");
  expect(host.initializeCalls).toBe(1);
  expect(host.connectingCalls).toBe(1);
  expect(host.presentationCalls).toEqual([
    {
      config: presentation(),
      initialMode: "read",
      theme: "light",
      viewMode: "read",
    },
  ]);
  expect(host.transport.serverTransports).toHaveLength(1);
  expect(host.transport.serverRequestActivations).toBe(1);
  expect(host.transport.runtime.getWsURL(testSessionId()).searchParams.get("embedded")).toBe(
    "true",
  );
  expect(host.transport.runtime.getSseURL(testSessionId()).searchParams.get("embedded")).toBe(
    "true",
  );
  expect(host.transport.runtime.headers()["Marimo-Session-Id"]).toBe("s_view01");
  expect(host.transport.runtime.sessionHeaders()["Marimo-Session-Id"]).toBe("s_view01");
  handle.updateServerTransport({
    ...serverTransport((url) => {
      url.searchParams.set("revision", "next");
      return url;
    }),
    serverToken: "next-token",
    url: "https://example.test/next/",
  });
  expect(host.transport.serverTransports).toHaveLength(2);
  expect(host.transport.serverTransports[1]).toMatchObject({
    serverToken: "next-token",
    url: "https://example.test/next/",
  });
  expect(host.transport.serverRequestActivations).toBe(2);
  expect(host.transport.serverRequestReleases).toBe(1);
  expect(host.transport.runtime.getWsURL(testSessionId()).searchParams.get("revision")).toBe(
    "next",
  );
  expect(host.transport.runtime.headers()["Marimo-Session-Id"]).toBe("s_view01");
  await expect(
    handle.invoke({ namespace: "studio", functionName: "ping", args: {} }),
  ).resolves.toEqual(functionResult);

  theme.set("dark");
  handle.update(presentation("light"));
  expect(host.presentationCalls.at(-1)).toEqual({
    config: presentation("light"),
    initialMode: "read",
    theme: "dark",
    viewMode: "read",
  });
  theme.set("light");
  theme.emit();
  expect(host.presentationCalls).toHaveLength(2);
  expect(host.themeCalls).toEqual([{ config: presentation("light"), theme: "light" }]);

  await act(async () => handle.dispose());
  handle.dispose();
  expect(target.childElementCount).toBe(0);
  expect(theme.listeners.size).toBe(0);
  expect(host.renderer?.disposeCalls).toBe(1);
  expect(globalThis.__MARIMO_STUDIO_SESSION_ID__).toBe("s_before");
  expect(host.transport.runtime.getWsURL).toBe(originalGetWsURL);
  expect(host.transport.runtime.getSseURL).toBe(originalGetSseURL);
  expect(host.transport.runtime.headers()["Marimo-Session-Id"]).toBe("s_native");
  expect(host.transport.serverRequestReleases).toBe(2);
});

test("model value requests become inert after final page and transport teardown", async () => {
  const assertInertAfter = async (
    teardown: (sender: ReturnType<typeof bindModelValueSenderToPage>) => void,
  ) => {
    let reject!: (cause: Error) => void;
    const pending = new Promise<null>((_resolve, fail) => {
      reject = fail;
    });
    const request = vi.fn(() => pending);
    const sender = bindModelValueSenderToPage(request);

    const inFlight = sender.send({ modelId: "model-1" });
    teardown(sender);
    reject(new TypeError("Failed to fetch"));

    await expect(inFlight).resolves.toBeNull();
    await expect(sender.send({ modelId: "model-2" })).resolves.toBeNull();
    expect(request).toHaveBeenCalledOnce();
    sender.dispose();
  };

  await assertInertAfter(() => {
    globalThis.dispatchEvent(new PageTransitionEvent("pagehide", { persisted: false }));
  });
  await assertInertAfter((sender) => sender.dispose());
});

test("model value request failures remain visible while the page is active", async () => {
  const failure = new TypeError("Failed to fetch");
  const request = vi.fn(async () => Promise.reject(failure));
  const sender = bindModelValueSenderToPage(request);

  globalThis.dispatchEvent(new PageTransitionEvent("pagehide", { persisted: true }));

  await expect(sender.send({ modelId: "model-1" })).rejects.toBe(failure);
  sender.dispose();
});

test("retries only failed disposal work", async () => {
  const target = root();
  const theme = createThemeSource();
  const host = new RuntimeHostDouble();
  const mountEmbeddedRuntime = createEmbeddedRuntimeMount(host);
  const originalGetWsURL = host.transport.runtime.getWsURL;
  const originalGetSseURL = host.transport.runtime.getSseURL;
  let releaseAttempts = 0;
  const source: EmbeddedThemeSource = {
    ...theme.source,
    subscribe(listener) {
      const release = theme.source.subscribe(listener);
      return () => {
        releaseAttempts += 1;
        if (releaseAttempts === 1) {
          throw new Error("theme release failed");
        }
        release();
      };
    },
  };
  let handle!: EmbeddedRuntimeHandle;

  await act(async () => {
    handle = mountEmbeddedRuntime({
      autoInstantiate: true,
      exposeSession: true,
      initialMode: "read",
      presentation: presentation(),
      render: () => null,
      root: target,
      theme: source,
      transport: serverTransport(),
      viewMode: "read",
    });
    await handle.initialized;
  });

  let disposalError: unknown;
  await act(async () => {
    try {
      handle.dispose();
    } catch (error) {
      disposalError = error;
    }
  });
  expect(disposalError).toEqual(new Error("theme release failed"));
  expect(host.transport.runtime.getWsURL).toBe(originalGetWsURL);
  expect(host.transport.runtime.getSseURL).toBe(originalGetSseURL);
  expect(host.renderer?.disposeCalls).toBe(1);
  expect(globalThis.__MARIMO_STUDIO_SESSION_ID__).toBeUndefined();

  handle.dispose();
  handle.dispose();
  expect(releaseAttempts).toBe(2);
  expect(theme.listeners.size).toBe(0);
  expect(host.renderer?.disposeCalls).toBe(1);
});

test("waits for WebAssembly readiness before reporting initialization", async () => {
  const target = root();
  const theme = createThemeSource();
  const host = new RuntimeHostDouble();
  const mountEmbeddedRuntime = createEmbeddedRuntimeMount(host);
  const waitForReady = vi.fn(
    async (workerInitialized: Promise<void>, invoke: EmbeddedRuntimeView["invoke"]) => {
      await workerInitialized;
      await invoke({ namespace: "studio", functionName: "ready", args: {} });
    },
  );
  let handle!: EmbeddedRuntimeHandle;

  await act(async () => {
    handle = mountEmbeddedRuntime({
      autoInstantiate: false,
      exposeSession: false,
      initialMode: "read",
      presentation: presentation(),
      render: () => null,
      root: target,
      theme: theme.source,
      transport: wasmTransport(waitForReady),
      viewMode: "read",
    });
    await handle.initialized;
  });

  expect(waitForReady).toHaveBeenCalledWith(
    host.transport.workerInitialized,
    handle.invoke,
    host.transport.executeWasmCells,
  );
  expect(host.transport.wasmTransports).toHaveLength(1);
  await act(async () => handle.dispose());
  expect(host.transport.wasmReleases).toBe(1);
});

test("reports synchronous transport failures through the handle", async () => {
  const target = root();
  const theme = createThemeSource();
  const host = new RuntimeHostDouble();
  const mountEmbeddedRuntime = createEmbeddedRuntimeMount(host);
  let handle!: EmbeddedRuntimeHandle;

  await act(async () => {
    handle = mountEmbeddedRuntime({
      autoInstantiate: false,
      exposeSession: false,
      initialMode: "read",
      presentation: presentation(),
      render: () => null,
      root: target,
      theme: theme.source,
      transport: wasmTransport(() => {
        throw new Error("transport unavailable");
      }),
      viewMode: "read",
    });
    await expect(handle.initialized).rejects.toThrow("transport unavailable");
  });

  await act(async () => handle.dispose());
});

test("allows one embedded runtime owner per mount boundary", async () => {
  const theme = createThemeSource();
  const host = new RuntimeHostDouble();
  const mountEmbeddedRuntime = createEmbeddedRuntimeMount(host);
  let first!: EmbeddedRuntimeHandle;
  await act(async () => {
    first = mountEmbeddedRuntime({
      autoInstantiate: false,
      exposeSession: false,
      initialMode: "read",
      presentation: presentation(),
      render: () => null,
      root: root(),
      theme: theme.source,
      transport: wasmTransport(),
      viewMode: "read",
    });
    await first.initialized;
  });

  expect(() =>
    mountEmbeddedRuntime({
      autoInstantiate: false,
      exposeSession: false,
      initialMode: "read",
      presentation: presentation(),
      render: () => null,
      root: root(),
      theme: theme.source,
      transport: wasmTransport(),
      viewMode: "read",
    }),
  ).toThrow("already mounted");

  await act(async () => first.dispose());

  let replacement!: EmbeddedRuntimeHandle;
  await act(async () => {
    replacement = mountEmbeddedRuntime({
      autoInstantiate: false,
      exposeSession: false,
      initialMode: "read",
      presentation: presentation(),
      render: () => null,
      root: root(),
      theme: theme.source,
      transport: wasmTransport(),
      viewMode: "read",
    });
    await replacement.initialized;
    replacement.dispose();
  });
});

test("retains runtime ownership when mount rollback cannot release a resource", () => {
  const cleanupError = new Error("theme rollback failed");
  const theme: EmbeddedThemeSource = {
    current: () => "light",
    subscribe: () => () => {
      throw cleanupError;
    },
  };
  const host = new RuntimeHostDouble();
  host.renderError = new Error("runtime render failed");
  const mountEmbeddedRuntime = createEmbeddedRuntimeMount(host);
  let failure: unknown;

  try {
    mountEmbeddedRuntime({
      autoInstantiate: false,
      exposeSession: false,
      initialMode: "read",
      presentation: presentation(),
      render: () => null,
      root: root(),
      theme,
      transport: wasmTransport(),
      viewMode: "read",
    });
  } catch (error) {
    failure = error;
  }

  expect(failure).toBeInstanceOf(AggregateError);
  if (!(failure instanceof AggregateError)) {
    throw new Error("Expected mount rollback to report an aggregate failure");
  }
  expect(failure.errors).toContain(cleanupError);
  expect(host.transport.wasmReleases).toBe(1);
  expect(() =>
    mountEmbeddedRuntime({
      autoInstantiate: false,
      exposeSession: false,
      initialMode: "read",
      presentation: presentation(),
      render: () => null,
      root: root(),
      theme,
      transport: wasmTransport(),
      viewMode: "read",
    }),
  ).toThrow("already mounted");
});

test("accepts JSON function results and rejects runtime-only values", () => {
  expect(parseEmbeddedJsonValue({ found: true, values: [1, "ready", null] })).toEqual({
    found: true,
    values: [1, "ready", null],
  });
  expect(() => parseEmbeddedJsonValue({ value: undefined })).toThrow();
});

test("composes the live kernel view and submits stdin through both Marimo paths", async () => {
  const cellId = CellId.create();
  const cell = {
    ...createCell({ id: cellId, name: "prompt" }),
    ...createCellRuntimeState(),
  };
  const kernel = new KernelDouble([cell]);
  const target = root();
  const renderRoot = createRoot(target);
  const initialized = Promise.resolve();
  const sessionId = testSessionId();
  let view: EmbeddedRuntimeView | undefined;

  await act(async () => {
    renderRoot.render(
      createElement(EmbeddedRuntimeViewComponent<KernelNotebook>, {
        autoInstantiate: false,
        initialized,
        kernel,
        render(runtime) {
          view = runtime;
          return createElement("div", {}, runtime.cells[0]?.name);
        },
        sessionId,
      }),
    );
    await initialized;
  });

  if (!view) {
    throw new Error("Expected the embedded kernel view to render");
  }
  const renderedView = view;
  expect(renderedView.initialization).toEqual({ state: "ready" });
  expect(renderedView.cells).toEqual([cell]);
  expect(renderedView.connection).toEqual({ state: "OPEN" });
  expect(kernel.connectionSessions.length).toBeGreaterThan(0);
  expect(new Set(kernel.connectionSessions)).toEqual(new Set([sessionId]));
  expect(new Set(kernel.connectionAutoInstantiate)).toEqual(new Set([false]));
  expect(kernel.startCalls).toBe(1);

  renderedView.submitStdin(cellId, "answer", 2);
  expect(kernel.setStdinResponse).toHaveBeenCalledWith({
    cellId,
    outputIndex: 2,
    response: "answer",
  });
  expect(kernel.sendStdin).toHaveBeenCalledWith({ text: "answer" });
  expect(() => renderedView.submitStdin("missing-cell", "answer", 2)).toThrow("unknown cell");

  await act(async () => renderRoot.unmount());
  expect(kernel.stopCalls).toBe(1);
});

test("mounts the exported Marimo runtime facade", async () => {
  window.__MARIMO_STATIC__ = { files: {} };
  const sessionId = await bootstrapSession(() => undefined);
  const target = root();
  const theme = createThemeSource();
  let view: EmbeddedRuntimeView | undefined;
  let handle: EmbeddedRuntimeHandle | undefined;

  try {
    await act(async () => {
      handle = mountMarimoRuntime({
        autoInstantiate: true,
        exposeSession: true,
        initialMode: "read",
        presentation: {
          appConfig: {},
          configOverrides: {},
          userConfig: {},
        },
        render(runtime) {
          view = runtime;
          return createElement("div", { "data-marimo-runtime": "" }, runtime.sessionId);
        },
        root: target,
        theme: theme.source,
        transport: serverTransport(),
        viewMode: "read",
      });
      await handle.initialized;
    });

    if (!view || !handle) {
      throw new Error("Expected the exported Marimo runtime facade to render");
    }
    expect(handle.sessionId).toBe(sessionId);
    expect(view.sessionId).toBe(sessionId);
    expect(view.initialization).toEqual({ state: "ready" });
    expect(view.connection).toEqual({ state: "OPEN" });
    expect(view.cells).toEqual([]);
    expect(target.textContent).toBe(sessionId);
    expect(globalThis.__MARIMO_STUDIO_SESSION_ID__).toBe(sessionId);
  } finally {
    const mounted = handle;
    if (mounted) {
      await act(async () => mounted.dispose());
    }
    delete window.__MARIMO_STATIC__;
  }
});

test("rotates an exported server transport through one runtime manager", async () => {
  window.__MARIMO_STATIC__ = { files: {} };
  await bootstrapSession(() => undefined);
  const theme = createThemeSource();
  let firstHandle: EmbeddedRuntimeHandle | undefined;
  let secondHandle: EmbeddedRuntimeHandle | undefined;

  try {
    await act(async () => {
      firstHandle = mountMarimoRuntime({
        autoInstantiate: true,
        exposeSession: true,
        initialMode: "read",
        presentation: presentation(),
        render: () => null,
        root: root(),
        theme: theme.source,
        transport: serverTransport(),
        viewMode: "read",
      });
      await firstHandle.initialized;
    });
    if (!firstHandle) {
      throw new Error("Expected the first exported runtime mount");
    }
    const mountedFirst = firstHandle;
    const firstManager = getRuntimeManager();
    const nextTransport: EmbeddedServerTransport = {
      ...serverTransport((url) => {
        url.searchParams.set("rotated", "true");
        return url;
      }),
      presentationSessionId: "s_view02",
      serverToken: "next-token",
      url: "https://next.example.test/base/",
    };

    mountedFirst.updateServerTransport(nextTransport);

    const rotatedManager = getRuntimeManager();
    expect(rotatedManager).toBe(firstManager);
    expect(rotatedManager.httpURL.toString()).toBe(nextTransport.url);
    expect(rotatedManager.headers()).toMatchObject({
      "Marimo-Server-Token": nextTransport.serverToken,
      "Marimo-Session-Id": nextTransport.presentationSessionId,
    });
    const socket = rotatedManager.getWsURL(mountedFirst.sessionId);
    expect(socket.origin).toBe("wss://next.example.test");
    expect(socket.searchParams.get("rotated")).toBe("true");

    await act(async () => mountedFirst.dispose());
    firstHandle = undefined;
    await act(async () => {
      secondHandle = mountMarimoRuntime({
        autoInstantiate: true,
        exposeSession: true,
        initialMode: "read",
        presentation: presentation(),
        render: () => null,
        root: root(),
        theme: theme.source,
        transport: serverTransport(),
        viewMode: "read",
      });
      await secondHandle.initialized;
    });
    expect(getRuntimeManager()).not.toBe(firstManager);
  } finally {
    if (firstHandle) {
      await act(async () => firstHandle?.dispose());
    }
    if (secondHandle) {
      await act(async () => secondHandle?.dispose());
    }
    delete window.__MARIMO_STATIC__;
  }
});
