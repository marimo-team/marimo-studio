import "@marimo-studio/marimo-frontend/style";
import "./style.css";
import type { RuntimeConfig } from "@marimo-studio/protocol/runtime-config";
import type { RuntimeSession } from "@marimo-studio/runtime";

import {
  connectionAtom,
  getSessionId,
  store,
  WebSocketState,
} from "@marimo-studio/marimo-frontend/runtime";
import { createRoot } from "react-dom/client";

import type { OutputReader } from "../outputs/reader";
import type { ValueReader } from "../values/reader";

import {
  configurePresentation,
  type InitialMode,
  initializePresentationRuntime,
  type ViewMode,
  watchPageTheme,
} from "./runtime-configuration";
import { RuntimeCellViews } from "./RuntimeCellViews";
import { RuntimeProviders } from "./RuntimeProviders";
import { exposeRuntimeSession } from "./session/expose-session";
import { startRuntimeTransport } from "./transport";

export interface RuntimeMountOptions {
  id: string;
  instance: string;
  initialMode: InitialMode;
  viewMode: ViewMode;
  exposeSession: boolean;
  configureTransport: () => void | Promise<void>;
  updateQuery: (query: string) => Promise<void>;
  valueReader: (sessionId: string, initialized: Promise<void>) => ValueReader;
  outputReader: (sessionId: string, initialized: Promise<void>) => OutputReader;
}

export const mountSharedRuntime = (
  config: RuntimeConfig,
  runtimeRoot: HTMLElement,
  options: RuntimeMountOptions,
): RuntimeSession => {
  let currentConfig = config;
  initializePresentationRuntime();
  configurePresentation(currentConfig, options.initialMode, options.viewMode);
  const sessionId = getSessionId();
  const initialized = startRuntimeTransport(options.configureTransport);
  store.set(connectionAtom, { state: WebSocketState.CONNECTING });
  const readValues = options.valueReader(sessionId, initialized);
  const readOutputs = options.outputReader(sessionId, initialized);

  let stopTheme = () => {};
  let stopExposingSession = () => {};
  let root: ReturnType<typeof createRoot> | undefined;
  try {
    stopTheme = watchPageTheme(() => currentConfig);
    root = createRoot(runtimeRoot);
    stopExposingSession = exposeRuntimeSession(sessionId, options.exposeSession);
    root.render(
      <RuntimeProviders>
        <RuntimeCellViews
          initialized={initialized}
          readOutputs={readOutputs}
          readValues={readValues}
          sessionId={sessionId}
        />
      </RuntimeProviders>,
    );
  } catch (error) {
    root?.unmount();
    stopExposingSession();
    stopTheme();
    throw error;
  }

  let disposed = false;

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
      if (disposed) {
        return;
      }
      disposed = true;
      root.unmount();
      stopExposingSession();
      stopTheme();
    },
  };
};
