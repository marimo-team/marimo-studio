import type { ReactNode } from "react";

import { Provider } from "jotai";
import { Suspense } from "react";

import type { EmbeddedJsonValue } from "./embedded-json.ts";

import { retainUnmountedControlValues } from "./embedded-control-state.ts";
import { UI_ELEMENT_REGISTRY } from "./upstream/controls.ts";
import {
  appConfigAtom,
  configOverridesAtom,
  ErrorBoundary,
  initialModeAtom,
  initializePlugins,
  LocaleProvider,
  ModalProvider,
  parseAppConfig,
  parseConfigOverrides,
  parseUserConfig,
  slotsController,
  SlotzProvider,
  store,
  ThemeProvider,
  Toaster,
  TooltipProvider,
  TracebackModalContainer,
  userConfigAtom,
  viewStateAtom,
} from "./upstream/presentation.ts";

export interface MarimoPresentationConfig {
  appConfig: EmbeddedJsonValue;
  configOverrides: EmbeddedJsonValue;
  userConfig: EmbeddedJsonValue;
}

export interface MarimoThemeSource {
  current(): "light" | "dark" | undefined;
  subscribe(listener: () => void): () => void;
}

export const MarimoPresentationProviders = ({
  children,
  runtimeOverlays,
}: {
  children: ReactNode;
  runtimeOverlays?: ReactNode;
}) => (
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
                  {runtimeOverlays}
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

export const initializeMarimoPresentation = (): void => {
  retainUnmountedControlValues(UI_ELEMENT_REGISTRY);
  if (!pluginsInitialized) {
    initializePlugins();
    pluginsInitialized = true;
  }
};

export const configureMarimoTheme = (
  config: MarimoPresentationConfig,
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

export const configureMarimoPresentation = (
  config: MarimoPresentationConfig,
  initialMode: "edit" | "read",
  viewMode: "present" | "read",
  theme: "light" | "dark" | undefined,
): void => {
  store.set(initialModeAtom, initialMode);
  store.set(viewStateAtom, { mode: viewMode, cellAnchor: null });
  store.set(configOverridesAtom, parseConfigOverrides(config.configOverrides));
  store.set(appConfigAtom, parseAppConfig(config.appConfig));
  configureMarimoTheme(config, theme);
};
