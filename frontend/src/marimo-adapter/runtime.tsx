import "@marimo-team/frontend/unstable_internal/css/index.css";
import "./style.css";

import { Provider } from "jotai";
import { createRoot } from "react-dom/client";

import { ErrorBoundary } from "@marimo-team/frontend/unstable_internal/components/editor/boundary/ErrorBoundary";
import { ModalProvider } from "@marimo-team/frontend/unstable_internal/components/modal/ImperativeModal";
import { TooltipProvider } from "@marimo-team/frontend/unstable_internal/components/ui/tooltip";
import {
  appConfigAtom,
  configOverridesAtom,
  userConfigAtom,
} from "@marimo-team/frontend/unstable_internal/core/config/config";
import {
  parseAppConfig,
  parseConfigOverrides,
  parseUserConfig,
} from "@marimo-team/frontend/unstable_internal/core/config/config-schema";
import {
  initialModeAtom,
  viewStateAtom,
} from "@marimo-team/frontend/unstable_internal/core/mode";
import { getSessionId } from "@marimo-team/frontend/unstable_internal/core/kernel/session";
import { connectionAtom } from "@marimo-team/frontend/unstable_internal/core/network/connection";
import { requestClientAtom } from "@marimo-team/frontend/unstable_internal/core/network/requests";
import { createNetworkRequests } from "@marimo-team/frontend/unstable_internal/core/network/requests-network";
import { createErrorToastingRequests } from "@marimo-team/frontend/unstable_internal/core/network/requests-toasting";
import {
  getRuntimeManager,
  runtimeConfigAtom,
} from "@marimo-team/frontend/unstable_internal/core/runtime/config";
import { store } from "@marimo-team/frontend/unstable_internal/core/state/jotai";
import { WebSocketState } from "@marimo-team/frontend/unstable_internal/core/websocket/types";
import { initializePlugins } from "@marimo-team/frontend/unstable_internal/plugins/plugins";
import { ThemeProvider } from "@marimo-team/frontend/unstable_internal/theme/ThemeProvider";

import { PAGE_THEME_EVENT, themeFromColorScheme } from "../page-theme";
import { getRuntimeConfig, type RuntimeConfig } from "../runtime-config";
import { RuntimeCellViews } from "./cell-views";
import { configureKioskTransport } from "./transport";

const preferredColorScheme = globalThis.matchMedia(
  "(prefers-color-scheme: dark)",
);

const initializeMovablePlugins = () => {
  const registry = globalThis.customElements;
  const define = registry.define;
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
    define.call(registry, name, constructor, options);
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

export const mountMarimoRuntime = (
  config: RuntimeConfig,
  runtimeRoot: HTMLElement,
) => {
  const sessionId = getSessionId();
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
  store.set(
    configOverridesAtom,
    parseConfigOverrides(config.configOverrides),
  );
  syncPageTheme(config);
  globalThis.addEventListener(PAGE_THEME_EVENT, () => {
    syncPageTheme(getRuntimeConfig());
  });
  preferredColorScheme.addEventListener("change", () => {
    syncPageTheme(getRuntimeConfig());
  });
  store.set(appConfigAtom, parseAppConfig(config.appConfig));
  store.set(connectionAtom, { state: WebSocketState.CONNECTING });
  store.set(
    requestClientAtom,
    createErrorToastingRequests(createNetworkRequests()),
  );

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
