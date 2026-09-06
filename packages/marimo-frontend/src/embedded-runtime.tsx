import type { ReactNode } from "react";

import { Provider } from "jotai";
import { Suspense } from "react";
import { createRoot } from "react-dom/client";

import type { EmbeddedJsonValue } from "./embedded-json.ts";
import type {
  EmbeddedRuntimeHost,
  EmbeddedRuntimeRenderer,
  EmbeddedTransportHost,
} from "./embedded-runtime-core.ts";
import type { EmbeddedRuntimeKernel } from "./embedded-runtime-view.tsx";
import type { SessionId } from "./session-bootstrap.ts";

import { retainUnmountedControlValues } from "./embedded-control-state.ts";
import { parseEmbeddedJsonValue } from "./embedded-json.ts";
import {
  bindModelValueSenderToPage,
  createEmbeddedRuntimeMount,
  createTransportInitializer,
} from "./embedded-runtime-core.ts";
import { EmbeddedRuntimeViewComponent } from "./embedded-runtime-view.tsx";
import {
  disposeProjectedOutputFunctionGate,
  type ProjectedOutputFunctionGate,
  type ProjectedOutputFunctionClient,
  startProjectedOutputFunctionGate,
} from "./projected-output-function-gate.ts";
import { currentSessionId } from "./session-bootstrap.ts";
import {
  type CellId,
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
  KernelStartupErrorModal,
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
  Toaster,
  TooltipProvider,
  TracebackModalContainer,
  useMarimoKernelConnection,
  useRequestClient,
  userConfigAtom,
  viewStateAtom,
  WebSocketState,
} from "./upstream/runtime.ts";
import { terminatePresentationWasmWorker } from "./wasm-worker-owner.ts";
import "./upstream/style.ts";

export { terminatePresentationWasmWorker } from "./wasm-worker-owner.ts";

export type EmbeddedConnectionState = "NOT_STARTED" | "CONNECTING" | "OPEN" | "CLOSING" | "CLOSED";

export type EmbeddedConnection =
  | { readonly state: Exclude<EmbeddedConnectionState, "CLOSED"> }
  | { readonly state: "CLOSED"; readonly code: string; readonly reason: string };

export type EmbeddedInitialization =
  | { state: "connecting" | "ready" }
  | { state: "error"; error: unknown };

export type { EmbeddedJsonValue };

export interface EmbeddedPresentationConfig {
  appConfig: EmbeddedJsonValue;
  configOverrides: EmbeddedJsonValue;
  userConfig: EmbeddedJsonValue;
}

export interface EmbeddedFunctionRequest {
  readonly namespace: string;
  readonly functionName: string;
  readonly args: { readonly [key: string]: EmbeddedJsonValue };
}

export type EmbeddedFunctionResult = EmbeddedJsonValue;

export type EmbeddedFunction = (
  request: EmbeddedFunctionRequest,
) => Promise<EmbeddedFunctionResult>;

export type EmbeddedRuntimeCell = ReturnType<typeof flattenTopLevelNotebookCells>[number];

export interface EmbeddedRuntimeView {
  readonly cells: EmbeddedRuntimeCell[];
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
  readonly presentationSessionId: string;
  readonly serverToken: string;
  readonly transformTransportURL: TransportURLTransform;
  readonly url: string;
}

export interface EmbeddedWasmTransport {
  readonly kind: "wasm";
  readonly autoInstantiate: boolean;
  readonly code: string;
  readonly filename: string;
  readonly url: string;
  readonly version: string;
  waitForReady(
    workerInitialized: Promise<void>,
    invoke: EmbeddedFunction,
    executeCells: EmbeddedCellExecutor,
  ): void | Promise<void>;
}

export interface EmbeddedExecutableCell {
  readonly id: string;
  readonly code: string;
}

export type EmbeddedCellExecutor = (cells: readonly EmbeddedExecutableCell[]) => Promise<void>;

export type EmbeddedTransport = EmbeddedServerTransport | EmbeddedWasmTransport;

export interface MountEmbeddedRuntimeOptions {
  readonly autoInstantiate: boolean;
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
  updateServerTransport(transport: EmbeddedServerTransport): void;
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
                <ModalProvider>
                  {children}
                  <Toaster />
                  <KernelStartupErrorModal />
                  <TracebackModalContainer />
                </ModalProvider>
              </LocaleProvider>
            </SlotzProvider>
          </TooltipProvider>
        </Suspense>
      </ErrorBoundary>
    </ThemeProvider>
  </Provider>
);

let pluginsInitialized = false;
let serverRuntimeConfig: { url: string; lazy: false; serverToken: string } | undefined;
let projectedOutputFunctionGate: ProjectedOutputFunctionGate | undefined;
let wasmFunctionClient: ProjectedOutputFunctionClient | undefined;

const currentProjectedOutputFunctionGate = (): ProjectedOutputFunctionGate => {
  if (!projectedOutputFunctionGate) {
    throw new Error("The projected output function gate has not started.");
  }
  return projectedOutputFunctionGate;
};

const initializeMovablePlugins = (): void => {
  const registry = globalThis.customElements;
  const define = registry.define.bind(registry);
  registry.define = (
    name: string,
    constructor: CustomElementConstructor,
    options?: ElementDefinitionOptions,
  ) => {
    if (name.startsWith("marimo-") && !("connectedMoveCallback" in constructor.prototype)) {
      Object.defineProperty(constructor.prototype, "connectedMoveCallback", {
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
  serverRuntimeConfig = undefined;
  projectedOutputFunctionGate = startProjectedOutputFunctionGate();
  wasmFunctionClient = undefined;
  retainUnmountedControlValues(UI_ELEMENT_REGISTRY);
  if (!pluginsInitialized) {
    initializeMovablePlugins();
  }
};

const configureTheme = (
  config: EmbeddedPresentationConfig,
  theme: "light" | "dark" | undefined,
): void => {
  const userConfig = parseUserConfig(config.userConfig);
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
  configureTheme(config, theme);
};

const invoke: EmbeddedFunction = async (request) =>
  parseEmbeddedJsonValue(await FUNCTIONS_REGISTRY.request(request));

type EmbeddedNotebook = ReturnType<typeof useNotebook>;

const embeddedRuntimeKernel: EmbeddedRuntimeKernel<EmbeddedNotebook> = {
  invoke,
  flattenCells: flattenTopLevelNotebookCells,
  startRuntime(sendComponentValues) {
    RuntimeState.INSTANCE.start(sendComponentValues);
  },
  stopRuntime() {
    RuntimeState.INSTANCE.stop();
  },
  useCellActions,
  useConnection({ autoInstantiate, sessionId, setCells }) {
    return useMarimoKernelConnection({
      autoInstantiate,
      setCells,
      sessionId,
    }).connection;
  },
  useNotebook,
  useRequestClient,
};

const transportHost: EmbeddedTransportHost = {
  activateServerRequests() {
    const previous = store.get(requestClientAtom);
    const network = createNetworkRequests();
    const modelValues = bindModelValueSenderToPage(network.sendModelValue);
    const functionClient = currentProjectedOutputFunctionGate().activateClient();
    const requests = createErrorToastingRequests({
      ...network,
      sendModelValue: modelValues.send,
    });
    try {
      store.set(requestClientAtom, requests);
    } catch (error) {
      functionClient.dispose();
      modelValues.dispose();
      throw error;
    }
    let active = true;
    return () => {
      if (!active) {
        return;
      }
      active = false;
      functionClient.dispose();
      modelValues.dispose();
      if (store.get(requestClientAtom) === requests) {
        store.set(requestClientAtom, previous);
      }
    };
  },
  prepareServer(transport) {
    if (serverRuntimeConfig === undefined) {
      serverRuntimeConfig = {
        url: transport.url,
        lazy: false,
        serverToken: transport.serverToken,
      };
      store.set(runtimeConfigAtom, serverRuntimeConfig);
    } else {
      serverRuntimeConfig.url = transport.url;
      serverRuntimeConfig.serverToken = transport.serverToken;
    }
    return getRuntimeManager();
  },
  prepareWasm(transport) {
    if (!transport.autoInstantiate) {
      const config = store.get(userConfigAtom);
      store.set(userConfigAtom, {
        ...config,
        runtime: { ...config.runtime, auto_instantiate: false },
      });
    }
    store.set(codeAtom, transport.code);
    store.set(filenameAtom, transport.filename);
    store.set(marimoVersionAtom, transport.version);
    store.set(runtimeConfigAtom, { url: transport.url, lazy: false, serverToken: "" });
    const bridge = PyodideBridge.INSTANCE;
    wasmFunctionClient?.dispose();
    const functionClient = currentProjectedOutputFunctionGate().activateClient();
    wasmFunctionClient = functionClient;
    store.set(requestClientAtom, resolveRequestClient());
    return bridge.initialized.promise;
  },
  releaseWasm() {
    wasmFunctionClient?.dispose();
    wasmFunctionClient = undefined;
    terminatePresentationWasmWorker();
  },
  async executeWasmCells(cells) {
    const cellIds = cells.map((cell) => {
      // SAFETY: This ID was compiled from the Marimo source loaded into this worker.
      return cell.id as CellId;
    });
    await PyodideBridge.INSTANCE.sendRun({
      cellIds,
      codes: cells.map((cell) => cell.code),
    });
  },
};

const initializeTransport = createTransportInitializer(transportHost, invoke);

const embeddedRuntimeHost: EmbeddedRuntimeHost = {
  invoke,
  configurePresentation,
  configureTheme,
  createRenderer(element) {
    const functionGate = currentProjectedOutputFunctionGate();
    const root = createRoot(element);
    const renderer: EmbeddedRuntimeRenderer = {
      render(initialized, renderView, sessionId, autoInstantiate) {
        root.render(
          <EmbeddedRuntimeProviders>
            <EmbeddedRuntimeViewComponent
              initialized={initialized}
              autoInstantiate={autoInstantiate}
              kernel={embeddedRuntimeKernel}
              render={renderView}
              sessionId={sessionId}
            />
          </EmbeddedRuntimeProviders>,
        );
      },
      dispose() {
        try {
          root.unmount();
        } finally {
          disposeProjectedOutputFunctionGate(functionGate);
          if (projectedOutputFunctionGate === functionGate) {
            projectedOutputFunctionGate = undefined;
          }
        }
      },
    };
    return renderer;
  },
  currentSessionId,
  initialize: initializeEmbeddedRuntime,
  initializeTransport,
  setConnecting() {
    store.set(connectionAtom, { state: WebSocketState.CONNECTING });
  },
};

export const mountEmbeddedRuntime = createEmbeddedRuntimeMount(embeddedRuntimeHost);
