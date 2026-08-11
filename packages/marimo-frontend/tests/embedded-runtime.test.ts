// @vitest-environment jsdom

import { act, createElement, type ReactNode } from "react";
import { beforeEach, expect, test, vi } from "vite-plus/test";

const mocks = vi.hoisted(() => {
  const runtimeManager = {
    getWsURL: vi.fn((_sessionId: string) => new URL("ws://example.test/ws?session_id=s_abc123")),
    getSseURL: vi.fn(
      (_sessionId: string) => new URL("https://example.test/sse?session_id=s_abc123"),
    ),
  };
  return {
    atoms: {
      appConfig: "app-config",
      code: "code",
      configOverrides: "config-overrides",
      connection: "connection",
      filename: "filename",
      initialMode: "initial-mode",
      marimoVersion: "marimo-version",
      requestClient: "request-client",
      runtimeConfig: "runtime-config",
      userConfig: "user-config",
      viewState: "view-state",
    },
    cells: [{ id: "cell-1" }],
    functionRequest: vi.fn(async () => ({ found: true })),
    initializePlugins: vi.fn(),
    retainControlValues: vi.fn(),
    runtimeManager,
    runtimeStart: vi.fn(),
    runtimeStop: vi.fn(),
    sendComponentValues: vi.fn(async () => undefined),
    sendStdin: vi.fn(async () => undefined),
    setCells: vi.fn(),
    setStdinResponse: vi.fn(),
    storeSet: vi.fn(),
    workerInitialized: Promise.resolve(),
  };
});

vi.mock("jotai", async () => {
  const { createElement } = await import("react");
  return {
    Provider: ({ children }: { children: ReactNode }) =>
      createElement("div", { "data-provider": "jotai" }, children),
  };
});

vi.mock("../src/embedded-control-state.ts", () => ({
  retainUnmountedControlValues: mocks.retainControlValues,
}));

vi.mock("../src/session-bootstrap.ts", () => ({
  currentSessionId: () => "s_abc123",
}));

vi.mock("../src/upstream/style.ts", () => ({}));

vi.mock("../src/upstream/controls.ts", () => ({
  UI_ELEMENT_REGISTRY: {},
}));

vi.mock("../src/upstream/cells.ts", () => ({
  flattenTopLevelNotebookCells: () => mocks.cells,
  RuntimeState: {
    INSTANCE: {
      start: mocks.runtimeStart,
      stop: mocks.runtimeStop,
    },
  },
  useCellActions: () => ({
    setCells: mocks.setCells,
    setStdinResponse: mocks.setStdinResponse,
  }),
  useNotebook: () => ({}),
}));

vi.mock("../src/upstream/runtime.ts", async () => {
  const { createElement } = await import("react");
  const provider =
    (name: string) =>
    ({ children }: { children: ReactNode }) =>
      createElement("div", { "data-provider": name }, children);
  return {
    appConfigAtom: mocks.atoms.appConfig,
    codeAtom: mocks.atoms.code,
    configOverridesAtom: mocks.atoms.configOverrides,
    connectionAtom: mocks.atoms.connection,
    createErrorToastingRequests: () => "server-requests",
    createNetworkRequests: () => "network-requests",
    ErrorBoundary: provider("error"),
    filenameAtom: mocks.atoms.filename,
    FUNCTIONS_REGISTRY: { request: mocks.functionRequest },
    getRuntimeManager: () => mocks.runtimeManager,
    initialModeAtom: mocks.atoms.initialMode,
    initializePlugins: mocks.initializePlugins,
    KernelStartupErrorModal: () => createElement("div", { "data-feedback": "startup" }),
    LocaleProvider: provider("locale"),
    marimoVersionAtom: mocks.atoms.marimoVersion,
    ModalProvider: provider("modal"),
    parseAppConfig: (value: unknown) => ({ parsedAppConfig: value }),
    parseConfigOverrides: (value: unknown) => ({ parsedConfigOverrides: value }),
    parseUserConfig: (value: unknown) => value,
    PyodideBridge: { INSTANCE: { initialized: { promise: mocks.workerInitialized } } },
    requestClientAtom: mocks.atoms.requestClient,
    resolveRequestClient: () => "wasm-requests",
    runtimeConfigAtom: mocks.atoms.runtimeConfig,
    slotsController: {},
    SlotzProvider: provider("slotz"),
    store: { set: mocks.storeSet },
    ThemeProvider: provider("theme"),
    Toaster: () => createElement("div", { "data-feedback": "toast" }),
    TooltipProvider: provider("tooltip"),
    TracebackModalContainer: () => createElement("div", { "data-feedback": "traceback" }),
    useMarimoKernelConnection: () => ({ connection: { state: "OPEN" } }),
    useRequestClient: () => ({
      sendComponentValues: mocks.sendComponentValues,
      sendStdin: mocks.sendStdin,
    }),
    userConfigAtom: mocks.atoms.userConfig,
    viewStateAtom: mocks.atoms.viewState,
    WebSocketState: {
      NOT_STARTED: "NOT_STARTED",
      CONNECTING: "CONNECTING",
      OPEN: "OPEN",
      CLOSING: "CLOSING",
      CLOSED: "CLOSED",
    },
  };
});

import {
  type EmbeddedRuntimeHandle,
  type EmbeddedRuntimeView,
  mountEmbeddedRuntime,
} from "../src/embedded-runtime.tsx";

const presentation = (theme = "system") => ({
  appConfig: { width: "full" },
  configOverrides: { runtime: "embedded" },
  userConfig: { display: { theme } },
});

const createThemeSource = () => {
  let current: "light" | "dark" | undefined = "light";
  const listeners = new Set<() => void>();
  return {
    source: {
      current: () => current,
      subscribe(listener: () => void) {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
    },
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

beforeEach(() => {
  vi.clearAllMocks();
  document.body.replaceChildren();
  delete (globalThis as typeof globalThis & { __MARIMO_STUDIO_SESSION_ID__?: string })
    .__MARIMO_STUDIO_SESSION_ID__;
});

test("mounts, updates, and disposes the server runtime through one handle", async () => {
  const target = root();
  const theme = createThemeSource();
  const originalGetWsURL = mocks.runtimeManager.getWsURL;
  const originalGetSseURL = mocks.runtimeManager.getSseURL;
  const browser = globalThis as typeof globalThis & {
    __MARIMO_STUDIO_SESSION_ID__?: string;
  };
  browser.__MARIMO_STUDIO_SESSION_ID__ = "s_before";
  let view: EmbeddedRuntimeView | undefined;
  let handle!: EmbeddedRuntimeHandle;

  await act(async () => {
    handle = mountEmbeddedRuntime({
      exposeSession: true,
      initialMode: "read",
      presentation: presentation(),
      render(runtime) {
        view = runtime;
        return createElement("div", { "data-runtime-view": "" }, runtime.sessionId);
      },
      root: target,
      theme: theme.source,
      transport: {
        kind: "server",
        serverToken: "token",
        transformTransportURL(url) {
          url.searchParams.set("embedded", "true");
          return url;
        },
        url: "https://example.test/base/",
      },
      viewMode: "read",
    });
    await handle.initialized;
  });

  expect(handle.sessionId).toBe("s_abc123");
  expect(browser.__MARIMO_STUDIO_SESSION_ID__).toBe("s_abc123");
  expect(view?.cells).toEqual(mocks.cells);
  expect(view?.connection.state).toBe("OPEN");
  expect(view?.initialization).toEqual({ state: "ready" });
  expect(
    Array.from(target.querySelectorAll<HTMLElement>("[data-provider]"), (element) =>
      element.getAttribute("data-provider"),
    ),
  ).toEqual(["jotai", "theme", "error", "tooltip", "slotz", "locale", "modal"]);
  expect(target.textContent).toContain("s_abc123");
  expect(
    Array.from(target.querySelectorAll<HTMLElement>("[data-feedback]"), (element) =>
      element.getAttribute("data-feedback"),
    ),
  ).toEqual(["toast", "startup", "traceback"]);
  expect(mocks.retainControlValues).toHaveBeenCalledOnce();
  expect(mocks.storeSet).toHaveBeenCalledWith(mocks.atoms.connection, { state: "CONNECTING" });
  expect(mocks.storeSet).toHaveBeenCalledWith(mocks.atoms.runtimeConfig, {
    lazy: false,
    serverToken: "token",
    url: "https://example.test/base/",
  });
  expect(mocks.runtimeManager.getWsURL("s_abc123").searchParams.get("embedded")).toBe("true");
  expect(mocks.runtimeManager.getSseURL("s_abc123").searchParams.get("embedded")).toBe("true");
  await expect(
    handle.invoke({ namespace: "studio", functionName: "ping", args: {} }),
  ).resolves.toEqual({ found: true });

  theme.set("dark");
  handle.update(presentation("light"));
  expect(mocks.storeSet).toHaveBeenLastCalledWith(mocks.atoms.userConfig, {
    display: { theme: "dark" },
  });
  theme.set("light");
  theme.emit();
  expect(mocks.storeSet).toHaveBeenLastCalledWith(mocks.atoms.userConfig, {
    display: { theme: "light" },
  });

  await act(async () => handle.dispose());
  handle.dispose();
  expect(target.childElementCount).toBe(0);
  expect(theme.listeners.size).toBe(0);
  expect(mocks.runtimeStop).toHaveBeenCalledOnce();
  expect(browser.__MARIMO_STUDIO_SESSION_ID__).toBe("s_before");
  expect(mocks.runtimeManager.getWsURL).toBe(originalGetWsURL);
  expect(mocks.runtimeManager.getSseURL).toBe(originalGetSseURL);
});

test("retries only failed disposal work", async () => {
  const target = root();
  const theme = createThemeSource();
  const originalGetWsURL = mocks.runtimeManager.getWsURL;
  const originalGetSseURL = mocks.runtimeManager.getSseURL;
  let releaseAttempts = 0;
  const source = {
    ...theme.source,
    subscribe(listener: () => void) {
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
      exposeSession: true,
      initialMode: "read",
      presentation: presentation(),
      render: () => null,
      root: target,
      theme: source,
      transport: {
        kind: "server",
        serverToken: "token",
        transformTransportURL: (url) => url,
        url: "https://example.test/base/",
      },
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
  expect(mocks.runtimeManager.getWsURL).toBe(originalGetWsURL);
  expect(mocks.runtimeManager.getSseURL).toBe(originalGetSseURL);
  expect(mocks.runtimeStop).toHaveBeenCalledOnce();
  expect(
    (globalThis as typeof globalThis & { __MARIMO_STUDIO_SESSION_ID__?: string })
      .__MARIMO_STUDIO_SESSION_ID__,
  ).toBeUndefined();

  handle.dispose();
  handle.dispose();
  expect(releaseAttempts).toBe(2);
  expect(theme.listeners.size).toBe(0);
});

test("waits for WebAssembly readiness before reporting initialization", async () => {
  const target = root();
  const theme = createThemeSource();
  const waitForReady = vi.fn(
    async (workerInitialized: Promise<void>, invoke: EmbeddedRuntimeView["invoke"]) => {
      await workerInitialized;
      await invoke({ namespace: "studio", functionName: "ready", args: {} });
    },
  );
  let handle!: EmbeddedRuntimeHandle;

  await act(async () => {
    handle = mountEmbeddedRuntime({
      exposeSession: false,
      initialMode: "read",
      presentation: presentation(),
      render: () => null,
      root: target,
      theme: theme.source,
      transport: {
        kind: "wasm",
        code: "print('ready')",
        filename: "notebook.py",
        url: "https://example.test/",
        version: "1.2.3",
        waitForReady,
      },
      viewMode: "read",
    });
    await handle.initialized;
  });

  expect(waitForReady).toHaveBeenCalledWith(mocks.workerInitialized, handle.invoke);
  expect(mocks.storeSet).toHaveBeenCalledWith(mocks.atoms.requestClient, "wasm-requests");
  expect(mocks.storeSet).toHaveBeenCalledWith(mocks.atoms.code, "print('ready')");
  await act(async () => handle.dispose());
});

test("reports synchronous transport failures through the handle", async () => {
  const target = root();
  const theme = createThemeSource();
  let handle!: EmbeddedRuntimeHandle;

  await act(async () => {
    handle = mountEmbeddedRuntime({
      exposeSession: false,
      initialMode: "read",
      presentation: presentation(),
      render: () => null,
      root: target,
      theme: theme.source,
      transport: {
        kind: "wasm",
        code: "",
        filename: "notebook.py",
        url: "https://example.test/",
        version: "1.2.3",
        waitForReady() {
          throw new Error("transport unavailable");
        },
      },
      viewMode: "read",
    });
    await expect(handle.initialized).rejects.toThrow("transport unavailable");
  });

  await act(async () => handle.dispose());
});

test("allows one embedded runtime owner per page", async () => {
  const theme = createThemeSource();
  let first!: EmbeddedRuntimeHandle;
  await act(async () => {
    first = mountEmbeddedRuntime({
      exposeSession: false,
      initialMode: "read",
      presentation: presentation(),
      render: () => null,
      root: root(),
      theme: theme.source,
      transport: {
        kind: "wasm",
        code: "",
        filename: "notebook.py",
        url: "https://example.test/",
        version: "1.2.3",
        waitForReady: () => undefined,
      },
      viewMode: "read",
    });
    await first.initialized;
  });

  expect(() =>
    mountEmbeddedRuntime({
      exposeSession: false,
      initialMode: "read",
      presentation: presentation(),
      render: () => null,
      root: root(),
      theme: theme.source,
      transport: {
        kind: "wasm",
        code: "",
        filename: "notebook.py",
        url: "https://example.test/",
        version: "1.2.3",
        waitForReady: () => undefined,
      },
      viewMode: "read",
    }),
  ).toThrow("already mounted");

  await act(async () => first.dispose());

  let replacement!: EmbeddedRuntimeHandle;
  await act(async () => {
    replacement = mountEmbeddedRuntime({
      exposeSession: false,
      initialMode: "read",
      presentation: presentation(),
      render: () => null,
      root: root(),
      theme: theme.source,
      transport: {
        kind: "wasm",
        code: "",
        filename: "notebook.py",
        url: "https://example.test/",
        version: "1.2.3",
        waitForReady: () => undefined,
      },
      viewMode: "read",
    });
    await replacement.initialized;
    replacement.dispose();
  });
});

test("retains runtime ownership when mount rollback cannot release a resource", () => {
  const cleanupError = new Error("theme rollback failed");
  const theme = {
    current: () => "light" as const,
    subscribe: () => () => {
      throw cleanupError;
    },
  };
  let failure: unknown;

  try {
    mountEmbeddedRuntime({
      exposeSession: false,
      initialMode: "read",
      presentation: presentation(),
      render: () => null,
      root: null as unknown as HTMLElement,
      theme,
      transport: {
        kind: "wasm",
        code: "",
        filename: "notebook.py",
        url: "https://example.test/",
        version: "1.2.3",
        waitForReady: () => undefined,
      },
      viewMode: "read",
    });
  } catch (error) {
    failure = error;
  }

  expect(failure).toBeInstanceOf(AggregateError);
  expect((failure as AggregateError).errors).toContain(cleanupError);
  expect(() =>
    mountEmbeddedRuntime({
      exposeSession: false,
      initialMode: "read",
      presentation: presentation(),
      render: () => null,
      root: root(),
      theme,
      transport: {
        kind: "wasm",
        code: "",
        filename: "notebook.py",
        url: "https://example.test/",
        version: "1.2.3",
        waitForReady: () => undefined,
      },
      viewMode: "read",
    }),
  ).toThrow("already mounted");
});
