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
import { createEmbeddedRuntimeMount, createTransportInitializer } from "./embedded-runtime-core.ts";
import { EmbeddedRuntimeViewComponent } from "./embedded-runtime-view.tsx";
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
import "./upstream/style.ts";

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
  useConnection({ sessionId, setCells }) {
    return useMarimoKernelConnection({
      autoInstantiate: true,
      setCells,
      sessionId,
    }).connection;
  },
  useNotebook,
  useRequestClient,
};

const transportHost: EmbeddedTransportHost = {
  activateServerRequests() {
    store.set(requestClientAtom, createErrorToastingRequests(createNetworkRequests()));
  },
  prepareServer(transport) {
    store.set(runtimeConfigAtom, {
      url: transport.url,
      lazy: false,
      serverToken: transport.serverToken,
    });
    return getRuntimeManager();
  },
  prepareWasm(transport) {
    store.set(codeAtom, transport.code);
    store.set(filenameAtom, transport.filename);
    store.set(marimoVersionAtom, transport.version);
    store.set(runtimeConfigAtom, { url: transport.url, lazy: false, serverToken: "" });
    const workerInitialized = PyodideBridge.INSTANCE.initialized.promise;
    store.set(requestClientAtom, resolveRequestClient());
    return workerInitialized;
  },
};

const initializeTransport = createTransportInitializer(transportHost, invoke);

const embeddedRuntimeHost: EmbeddedRuntimeHost = {
  invoke,
  configurePresentation,
  configureTheme,
  createRenderer(element) {
    const root = createRoot(element);
    const renderer: EmbeddedRuntimeRenderer = {
      render(initialized, renderView, sessionId) {
        root.render(
          <EmbeddedRuntimeProviders>
            <EmbeddedRuntimeViewComponent
              initialized={initialized}
              kernel={embeddedRuntimeKernel}
              render={renderView}
              sessionId={sessionId}
            />
          </EmbeddedRuntimeProviders>,
        );
      },
      dispose() {
        root.unmount();
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
