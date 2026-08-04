import type { RuntimeConfig } from "@marimo-studio/protocol/runtime-config";

import { UI_ELEMENT_REGISTRY } from "@marimo-studio/marimo-frontend/controls";
import {
  appConfigAtom,
  configOverridesAtom,
  initializePlugins,
  initialModeAtom,
  parseAppConfig,
  parseConfigOverrides,
  parseUserConfig,
  store,
  userConfigAtom,
  viewStateAtom,
} from "@marimo-studio/marimo-frontend/runtime";

import { PAGE_THEME_EVENT, themeFromColorScheme } from "../document/theme";
import { retainUnmountedUIValues } from "./peer-controls";

export type InitialMode = "edit" | "read";
export type ViewMode = "present" | "read";

const preferredColorScheme = globalThis.matchMedia("(prefers-color-scheme: dark)");

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
  } finally {
    registry.define = define;
  }
};

const syncPageTheme = (config: RuntimeConfig): void => {
  const userConfig = parseUserConfig(config.userConfig);
  const pageTheme = themeFromColorScheme(
    globalThis.getComputedStyle(document.documentElement).colorScheme,
    preferredColorScheme.matches,
  );
  const themedConfig = pageTheme
    ? {
        ...userConfig,
        display: { ...userConfig.display, theme: pageTheme },
      }
    : userConfig;
  store.set(userConfigAtom, themedConfig);
};

export const initializePresentationRuntime = (): void => {
  retainUnmountedUIValues(UI_ELEMENT_REGISTRY);
  initializeMovablePlugins();
};

export const configurePresentation = (
  config: RuntimeConfig,
  initialMode: InitialMode,
  viewMode: ViewMode,
): void => {
  store.set(initialModeAtom, initialMode);
  store.set(viewStateAtom, { mode: viewMode, cellAnchor: null });
  store.set(configOverridesAtom, parseConfigOverrides(config.configOverrides));
  store.set(appConfigAtom, parseAppConfig(config.appConfig));
  syncPageTheme(config);
};

export const watchPageTheme = (config: () => RuntimeConfig): (() => void) => {
  const sync = () => syncPageTheme(config());
  globalThis.addEventListener(PAGE_THEME_EVENT, sync);
  preferredColorScheme.addEventListener("change", sync);
  return () => {
    globalThis.removeEventListener(PAGE_THEME_EVENT, sync);
    preferredColorScheme.removeEventListener("change", sync);
  };
};
