import "@marimo-studio/marimo-frontend/style";
import "./style.css";
import type { RuntimeConfig } from "@marimo-studio/protocol/runtime-config";
import type { RuntimeSession } from "@marimo-studio/runtime";

import { UI_ELEMENT_REGISTRY } from "@marimo-studio/marimo-frontend/controls";
import {
  appConfigAtom,
  configOverridesAtom,
  connectionAtom,
  ErrorBoundary,
  getSessionId,
  initializePlugins,
  initialModeAtom,
  ModalProvider,
  parseAppConfig,
  parseConfigOverrides,
  parseUserConfig,
  store,
  ThemeProvider,
  TooltipProvider,
  userConfigAtom,
  viewStateAtom,
  WebSocketState,
} from "@marimo-studio/marimo-frontend/runtime";
import { Provider } from "jotai";
import { createRoot } from "react-dom/client";

import type { ValueReader } from "../values/reader";

import { PAGE_THEME_EVENT, themeFromColorScheme } from "../document/theme";
import { RuntimeCellViews } from "./cell-views";
import { retainUnmountedUIValues } from "./peer-controls";

type InitialMode = "edit" | "read";
type ViewMode = "present" | "read";

export interface RuntimeMountOptions {
  id: string;
  instance: string;
  initialMode: InitialMode;
  viewMode: ViewMode;
  exposeSession: boolean;
  configureTransport(): void | Promise<void>;
  updateQuery(query: string): Promise<void>;
  valueReader(sessionId: string, initialized: Promise<void>): ValueReader;
}

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

const configurePresentation = (
  config: RuntimeConfig,
  initialMode: InitialMode,
  viewMode: ViewMode,
) => {
  store.set(initialModeAtom, initialMode);
  store.set(viewStateAtom, { mode: viewMode, cellAnchor: null });
  store.set(configOverridesAtom, parseConfigOverrides(config.configOverrides));
  store.set(appConfigAtom, parseAppConfig(config.appConfig));
  syncPageTheme(config);
};

export const mountSharedRuntime = (
  config: RuntimeConfig,
  runtimeRoot: HTMLElement,
  options: RuntimeMountOptions,
): RuntimeSession => {
  const sessionId = getSessionId();
  let currentConfig = config;
  retainUnmountedUIValues(UI_ELEMENT_REGISTRY);
  initializeMovablePlugins();
  configurePresentation(currentConfig, options.initialMode, options.viewMode);
  const initialized = Promise.resolve(options.configureTransport());
  store.set(connectionAtom, { state: WebSocketState.CONNECTING });

  const syncTheme = () => syncPageTheme(currentConfig);
  globalThis.addEventListener(PAGE_THEME_EVENT, syncTheme);
  preferredColorScheme.addEventListener("change", syncTheme);

  const root = createRoot(runtimeRoot);
  root.render(
    <Provider store={store}>
      <ThemeProvider>
        <ErrorBoundary>
          <TooltipProvider>
            <ModalProvider>
              <RuntimeCellViews
                exposeSession={options.exposeSession}
                initialized={initialized}
                readValues={options.valueReader(sessionId, initialized)}
                sessionId={sessionId}
              />
            </ModalProvider>
          </TooltipProvider>
        </ErrorBoundary>
      </ThemeProvider>
    </Provider>,
  );

  return {
    id: options.id,
    sessionId: options.exposeSession ? sessionId : undefined,
    update(next) {
      if (next.runtime.id !== options.id || next.runtime.instance !== options.instance) {
        return "reload";
      }
      currentConfig = next;
      configurePresentation(next, options.initialMode, options.viewMode);
      return "applied";
    },
    updateQuery: (query) => options.updateQuery(query),
    dispose() {
      root.unmount();
      globalThis.removeEventListener(PAGE_THEME_EVENT, syncTheme);
      preferredColorScheme.removeEventListener("change", syncTheme);
    },
  };
};
