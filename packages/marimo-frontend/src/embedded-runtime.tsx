import type { ReactNode } from "react";

import { Provider } from "jotai";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";

import type { RuntimeCell } from "./cell-presentation.tsx";
import type { SessionId } from "./session-bootstrap.ts";

import { retainUnmountedControlValues } from "./embedded-control-state.ts";
import { currentSessionId } from "./session-bootstrap.ts";
import {
  flattenTopLevelNotebookCells,
  RuntimeState,
  useCellActions,
  useNotebook,
} from "./upstream/cells.ts";
import { UI_ELEMENT_REGISTRY } from "./upstream/controls.ts";
import {
  appConfigAtom,
  codeAtom,
  configOverridesAtom,
  connectionAtom,
  createErrorToastingRequests,
  createNetworkRequests,
  ErrorBoundary,
  filenameAtom,
  FUNCTIONS_REGISTRY,
  getRuntimeManager,
  initialModeAtom,
  initializePlugins,
  LocaleProvider,
  marimoVersionAtom,
  ModalProvider,
  parseAppConfig,
  parseConfigOverrides,
  parseUserConfig,
  PyodideBridge,
  requestClientAtom,
  resolveRequestClient,
  runtimeConfigAtom,
  slotsController,
  SlotzProvider,
  store,
  ThemeProvider,
  TooltipProvider,
  useMarimoKernelConnection,
  useRequestClient,
  userConfigAtom,
  viewStateAtom,
  WebSocketState,
} from "./upstream/runtime.ts";
import "./upstream/style.ts";

export type EmbeddedConnectionState = "NOT_STARTED" | "CONNECTING" | "OPEN" | "CLOSING" | "CLOSED";

export type EmbeddedConnection =
  | { state: Exclude<EmbeddedConnectionState, "CLOSED"> }
  | { state: "CLOSED"; code: string; reason: string };

export type EmbeddedInitialization =
  | { state: "connecting" | "ready" }
  | { state: "error"; error: unknown };

export interface EmbeddedPresentationConfig {
  appConfig: unknown;
  configOverrides: unknown;
  userConfig: unknown;
}

export interface EmbeddedFunctionRequest {
  namespace: string;
  functionName: string;
  args: Record<string, unknown>;
}

export type EmbeddedFunction = (request: EmbeddedFunctionRequest) => Promise<unknown>;

export interface EmbeddedRuntimeView {
  readonly cells: RuntimeCell[];
  readonly connection: EmbeddedConnection;
  readonly initialization: EmbeddedInitialization;
  readonly initialized: Promise<void>;
  readonly invoke: EmbeddedFunction;
  readonly sessionId: SessionId;
  readonly submitStdin: (cellId: string, text: string, outputIndex: number) => void;
}

export interface EmbeddedThemeSource {
  current(): "light" | "dark" | undefined;
  subscribe(listener: () => void): () => void;
}

type TransportURLTransform = (url: URL) => URL;

export interface EmbeddedServerTransport {
  readonly kind: "server";
  readonly serverToken: string;
  readonly transformTransportURL: TransportURLTransform;
  readonly url: string;
}

export interface EmbeddedWasmTransport {
  readonly kind: "wasm";
  readonly code: string;
  readonly filename: string;
  readonly url: string;
  readonly version: string;
  waitForReady(workerInitialized: Promise<void>, invoke: EmbeddedFunction): void | Promise<void>;
}

export type EmbeddedTransport = EmbeddedServerTransport | EmbeddedWasmTransport;

export interface MountEmbeddedRuntimeOptions {
  readonly exposeSession: boolean;
  readonly initialMode: "edit" | "read";
  readonly presentation: EmbeddedPresentationConfig;
  readonly render: (runtime: EmbeddedRuntimeView) => ReactNode;
  readonly root: HTMLElement;
  readonly theme: EmbeddedThemeSource;
  readonly transport: EmbeddedTransport;
  readonly viewMode: "present" | "read";
}

export interface EmbeddedRuntimeHandle {
  readonly initialized: Promise<void>;
  readonly invoke: EmbeddedFunction;
  readonly sessionId: SessionId;
  update(presentation: EmbeddedPresentationConfig): void;
  dispose(): void;
}

const EmbeddedRuntimeProviders = ({ children }: { children: ReactNode }) => (
  <Provider store={store}>
    <ThemeProvider>
      <ErrorBoundary>
        <Suspense>
          <TooltipProvider>
            <SlotzProvider controller={slotsController}>
              <LocaleProvider>
                <ModalProvider>{children}</ModalProvider>
              </LocaleProvider>
            </SlotzProvider>
          </TooltipProvider>
        </Suspense>
      </ErrorBoundary>
    </ThemeProvider>
  </Provider>
);

let pluginsInitialized = false;

const initializeMovablePlugins = (): void => {
  const registry = globalThis.customElements;
  const define = registry.define.bind(registry);
  registry.define = (
    name: string,
    constructor: CustomElementConstructor,
    options?: ElementDefinitionOptions,
  ) => {
    const prototype = constructor.prototype as HTMLElement & {
      connectedMoveCallback?: () => void;
    };
    if (name.startsWith("marimo-") && !prototype.connectedMoveCallback) {
      Object.defineProperty(prototype, "connectedMoveCallback", {
        configurable: true,
        value() {},
      });
    }
    define(name, constructor, options);
  };
  try {
    initializePlugins();
    pluginsInitialized = true;
  } finally {
    registry.define = define;
  }
};

const initializeEmbeddedRuntime = (): void => {
  retainUnmountedControlValues(UI_ELEMENT_REGISTRY);
  if (!pluginsInitialized) {
    initializeMovablePlugins();
  }
};

const configureTheme = (userConfigValue: unknown, theme: "light" | "dark" | undefined): void => {
  const userConfig = parseUserConfig(userConfigValue);
  store.set(
    userConfigAtom,
    theme
      ? {
          ...userConfig,
          display: { ...userConfig.display, theme },
        }
      : userConfig,
  );
};

const configurePresentation = (
  config: EmbeddedPresentationConfig,
  initialMode: "edit" | "read",
  viewMode: "present" | "read",
  theme: "light" | "dark" | undefined,
): void => {
  store.set(initialModeAtom, initialMode);
  store.set(viewStateAtom, { mode: viewMode, cellAnchor: null });
  store.set(configOverridesAtom, parseConfigOverrides(config.configOverrides));
  store.set(appConfigAtom, parseAppConfig(config.appConfig));
  configureTheme(config.userConfig, theme);
};

type RuntimeManager = ReturnType<typeof getRuntimeManager>;

interface TransportURLPatch {
  readonly getSseURL: RuntimeManager["getSseURL"];
  readonly getWsURL: RuntimeManager["getWsURL"];
}

const transportURLPatches = new WeakMap<object, TransportURLPatch>();

const configureTransportURLs = (
  runtime: RuntimeManager,
  transformTransportURL: TransportURLTransform,
): (() => void) => {
  if (transportURLPatches.has(runtime)) {
    throw new Error("The embedded runtime transport URLs already have an owner");
  }
  const originalGetWsURL = Reflect.get(runtime, "getWsURL") as RuntimeManager["getWsURL"];
  const originalGetSseURL = Reflect.get(runtime, "getSseURL") as RuntimeManager["getSseURL"];
  const getWsURL: RuntimeManager["getWsURL"] = (sessionId) =>
    transformTransportURL(originalGetWsURL.call(runtime, sessionId));
  const getSseURL: RuntimeManager["getSseURL"] = (sessionId) =>
    transformTransportURL(originalGetSseURL.call(runtime, sessionId));
  const patch = { getSseURL, getWsURL };
  transportURLPatches.set(runtime, patch);
  runtime.getWsURL = getWsURL;
  runtime.getSseURL = getSseURL;

  let released = false;
  return () => {
    if (released) {
      return;
    }
    if (
      transportURLPatches.get(runtime) !== patch ||
      runtime.getWsURL !== getWsURL ||
      runtime.getSseURL !== getSseURL
    ) {
      throw new Error("The embedded runtime transport URL methods changed before disposal");
    }
    runtime.getWsURL = originalGetWsURL;
    runtime.getSseURL = originalGetSseURL;
    transportURLPatches.delete(runtime);
    released = true;
  };
};

const invoke: EmbeddedFunction = (request) =>
  FUNCTIONS_REGISTRY.request(
    request as Parameters<typeof FUNCTIONS_REGISTRY.request>[0],
  ) as Promise<unknown>;

const initializeTransport = (
  transport: EmbeddedTransport,
): { initialized: Promise<void>; release: () => void } => {
  let release = () => {};
  try {
    if (transport.kind === "server") {
      store.set(runtimeConfigAtom, {
        url: transport.url,
        lazy: false,
        serverToken: transport.serverToken,
      });
      release = configureTransportURLs(getRuntimeManager(), transport.transformTransportURL);
      store.set(requestClientAtom, createErrorToastingRequests(createNetworkRequests()));
      return { initialized: Promise.resolve(), release };
    }

    store.set(codeAtom, transport.code);
    store.set(filenameAtom, transport.filename);
    store.set(marimoVersionAtom, transport.version);
    store.set(runtimeConfigAtom, { url: transport.url, lazy: false, serverToken: "" });
    const workerInitialized = PyodideBridge.INSTANCE.initialized.promise;
    store.set(requestClientAtom, resolveRequestClient());
    return {
      initialized: Promise.resolve(transport.waitForReady(workerInitialized, invoke)),
      release,
    };
  } catch (error) {
    try {
      release();
    } catch (releaseError) {
      return {
        initialized: Promise.reject(new AggregateError([error, releaseError])),
        release,
      };
    }
    return { initialized: Promise.reject(error), release };
  }
};

const useInitialization = (initialized: Promise<void>): EmbeddedInitialization => {
  const [state, setState] = useState<EmbeddedInitialization>({ state: "connecting" });

  useEffect(() => {
    let active = true;
    initialized.then(
      () => {
        if (active) {
          setState({ state: "ready" });
        }
      },
      (error: unknown) => {
        if (active) {
          setState({ state: "error", error });
        }
      },
    );
    return () => {
      active = false;
    };
  }, [initialized]);

  return state;
};

const EmbeddedRuntime = ({
  initialized,
  render,
  sessionId,
}: {
  initialized: Promise<void>;
  render: (runtime: EmbeddedRuntimeView) => ReactNode;
  sessionId: SessionId;
}) => {
  const { setCells, setStdinResponse } = useCellActions();
  const { sendComponentValues, sendStdin } = useRequestClient();
  const notebook = useNotebook();
  const initialization = useInitialization(initialized);

  useEffect(() => {
    RuntimeState.INSTANCE.start(sendComponentValues);
    return () => RuntimeState.INSTANCE.stop();
  }, [sendComponentValues]);

  const { connection } = useMarimoKernelConnection({
    autoInstantiate: true,
    setCells,
    sessionId: sessionId as unknown as Parameters<typeof useMarimoKernelConnection>[0]["sessionId"],
  });
  const cells = useMemo(() => flattenTopLevelNotebookCells(notebook) as RuntimeCell[], [notebook]);
  const submitStdin = useCallback(
    (cellId: string, text: string, outputIndex: number) => {
      setStdinResponse({
        cellId: cellId as RuntimeCell["id"] & Parameters<typeof setStdinResponse>[0]["cellId"],
        response: text,
        outputIndex,
      });
      void sendStdin({ text });
    },
    [sendStdin, setStdinResponse],
  );

  return render({
    cells,
    connection: connection as unknown as EmbeddedConnection,
    initialization,
    initialized,
    invoke,
    sessionId,
    submitStdin,
  });
};

const exposeSession = (sessionId: SessionId, enabled: boolean): (() => void) => {
  if (!enabled) {
    return () => {};
  }
  const browser = globalThis as typeof globalThis & {
    __MARIMO_STUDIO_SESSION_ID__?: string;
  };
  const previous = browser.__MARIMO_STUDIO_SESSION_ID__;
  browser.__MARIMO_STUDIO_SESSION_ID__ = sessionId;
  return () => {
    if (browser.__MARIMO_STUDIO_SESSION_ID__ !== sessionId) {
      return;
    }
    if (previous === undefined) {
      delete browser.__MARIMO_STUDIO_SESSION_ID__;
    } else {
      browser.__MARIMO_STUDIO_SESSION_ID__ = previous;
    }
  };
};

const runDisposers = (disposers: Set<() => void>): unknown[] => {
  const errors: unknown[] = [];
  for (const dispose of disposers) {
    try {
      dispose();
      disposers.delete(dispose);
    } catch (error) {
      errors.push(error);
    }
  }
  return errors;
};

const throwDisposalErrors = (errors: unknown[]): void => {
  if (errors.length === 1) {
    throw errors[0];
  }
  if (errors.length > 1) {
    throw new AggregateError(errors, "Embedded runtime disposal failed");
  }
};

export const mountEmbeddedRuntime = (
  options: MountEmbeddedRuntimeOptions,
): EmbeddedRuntimeHandle => {
  let presentation = options.presentation;
  initializeEmbeddedRuntime();
  configurePresentation(
    presentation,
    options.initialMode,
    options.viewMode,
    options.theme.current(),
  );
  const sessionId = currentSessionId();
  const transport = initializeTransport(options.transport);
  const initialized = transport.initialized;

  let stopTheme = () => {};
  let stopExposingSession = () => {};
  let root: ReturnType<typeof createRoot> | undefined;
  const disposers = new Set<() => void>([
    () => root?.unmount(),
    () => stopExposingSession(),
    () => stopTheme(),
    () => transport.release(),
  ]);
  try {
    store.set(connectionAtom, { state: WebSocketState.CONNECTING });
    const syncTheme = () => configureTheme(presentation.userConfig, options.theme.current());
    stopTheme = options.theme.subscribe(syncTheme);
    root = createRoot(options.root);
    stopExposingSession = exposeSession(sessionId, options.exposeSession);
    root.render(
      <EmbeddedRuntimeProviders>
        <EmbeddedRuntime initialized={initialized} render={options.render} sessionId={sessionId} />
      </EmbeddedRuntimeProviders>,
    );
  } catch (error) {
    const cleanupErrors = runDisposers(disposers);
    if (cleanupErrors.length > 0) {
      throw new AggregateError(
        [error, ...cleanupErrors],
        "Embedded runtime mount and rollback failed",
      );
    }
    throw error;
  }

  let disposing = false;
  return {
    initialized,
    invoke,
    sessionId,
    update(next) {
      if (disposing) {
        return;
      }
      presentation = next;
      configurePresentation(
        presentation,
        options.initialMode,
        options.viewMode,
        options.theme.current(),
      );
    },
    dispose() {
      if (disposers.size === 0) {
        return;
      }
      disposing = true;
      throwDisposalErrors(runDisposers(disposers));
    },
  };
};
