import "@marimo-studio/marimo-frontend/style";
import "./style.css";
import { UI_ELEMENT_REGISTRY } from "@marimo-studio/marimo-frontend/controls";
import {
  appConfigAtom,
  configOverridesAtom,
  connectionAtom,
  createErrorToastingRequests,
  createNetworkRequests,
  ErrorBoundary,
  getRuntimeManager,
  getSessionId,
  initializePlugins,
  initialModeAtom,
  ModalProvider,
  parseAppConfig,
  parseConfigOverrides,
  parseUserConfig,
  requestClientAtom,
  runtimeConfigAtom,
  store,
  ThemeProvider,
  TooltipProvider,
  userConfigAtom,
  viewStateAtom,
  WebSocketState,
} from "@marimo-studio/marimo-frontend/runtime";
import { Provider } from "jotai";
import { createRoot } from "react-dom/client";

import { PAGE_THEME_EVENT, themeFromColorScheme } from "../document/theme";
import { getRuntimeConfig, type RuntimeConfig } from "../runtime-config/index";
import { RuntimeCellViews } from "./cell-views";
import { retainUnmountedUIValues } from "./peer-controls";
import { configureKioskTransport } from "./transport";

const preferredColorScheme = globalThis.matchMedia("(prefers-color-scheme: dark)");

const initializeMovablePlugins = () => {
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
  } finally {
    registry.define = define;
  }
};

const syncPageTheme = (config: RuntimeConfig) => {
  const userConfig = parseUserConfig(config.userConfig);
  const pageTheme = themeFromColorScheme(
    globalThis.getComputedStyle(document.documentElement).colorScheme,
    preferredColorScheme.matches,
  );
  store.set(
    userConfigAtom,
    pageTheme
      ? {
          ...userConfig,
          display: { ...userConfig.display, theme: pageTheme },
        }
      : userConfig,
  );
};

export const mountMarimoRuntime = (config: RuntimeConfig, runtimeRoot: HTMLElement) => {
  const sessionId = getSessionId();
  retainUnmountedUIValues(UI_ELEMENT_REGISTRY);
  initializeMovablePlugins();

  store.set(runtimeConfigAtom, {
    url: new URL(config.runtimeUrl, globalThis.location.origin).toString(),
    // Marimo uses this flag to defer a remote connection. Native local run
    // pages connect immediately, while graph laziness remains kernel-owned.
    lazy: false,
    serverToken: config.serverToken,
  });
  // Marimo selects kiosk consumers from transport query parameters. Apply the
  // marker at that boundary so the HTTP API keeps the configured base URL.
  configureKioskTransport(getRuntimeManager(), config.mode === "edit");
  const initialMode = config.mode === "edit" ? "edit" : "read";
  const viewMode = config.mode === "edit" ? "present" : "read";
  store.set(initialModeAtom, initialMode);
  store.set(viewStateAtom, { mode: viewMode, cellAnchor: null });
  store.set(configOverridesAtom, parseConfigOverrides(config.configOverrides));
  syncPageTheme(config);
  globalThis.addEventListener(PAGE_THEME_EVENT, () => {
    syncPageTheme(getRuntimeConfig());
  });
  preferredColorScheme.addEventListener("change", () => {
    syncPageTheme(getRuntimeConfig());
  });
  store.set(appConfigAtom, parseAppConfig(config.appConfig));
  store.set(connectionAtom, { state: WebSocketState.CONNECTING });
  store.set(requestClientAtom, createErrorToastingRequests(createNetworkRequests()));

  createRoot(runtimeRoot).render(
    <Provider store={store}>
      <ThemeProvider>
        <ErrorBoundary>
          <TooltipProvider>
            <ModalProvider>
              <RuntimeCellViews sessionId={sessionId} />
            </ModalProvider>
          </TooltipProvider>
        </ErrorBoundary>
      </ThemeProvider>
    </Provider>,
  );
  return sessionId;
};
