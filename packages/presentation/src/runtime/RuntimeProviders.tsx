import type { ReactNode } from "react";

import {
  ErrorBoundary,
  ModalProvider,
  store,
  ThemeProvider,
  TooltipProvider,
} from "@marimo-studio/marimo-frontend/runtime";
import { Provider } from "jotai";

export const RuntimeProviders = ({ children }: { children: ReactNode }) => (
  <Provider store={store}>
    <ThemeProvider>
      <ErrorBoundary>
        <TooltipProvider>
          <ModalProvider>{children}</ModalProvider>
        </TooltipProvider>
      </ErrorBoundary>
    </ThemeProvider>
  </Provider>
);
