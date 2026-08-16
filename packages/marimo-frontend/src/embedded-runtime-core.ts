import type { ReactNode } from "react";

import type {
  EmbeddedFunction,
  EmbeddedPresentationConfig,
  EmbeddedRuntimeHandle,
  EmbeddedRuntimeView,
  EmbeddedServerTransport,
  EmbeddedTransport,
  EmbeddedWasmTransport,
  MountEmbeddedRuntimeOptions,
} from "./embedded-runtime.tsx";
import type { SessionId } from "./session-bootstrap.ts";

export interface InitializedTransport {
  readonly initialized: Promise<void>;
  readonly release: () => void;
}

export interface EmbeddedRuntimeRenderer {
  render(
    initialized: Promise<void>,
    renderView: (runtime: EmbeddedRuntimeView) => ReactNode,
    sessionId: SessionId,
  ): void;
  dispose(): void;
}

export interface EmbeddedRuntimeHost {
  readonly invoke: EmbeddedFunction;
  configurePresentation(
    config: EmbeddedPresentationConfig,
    initialMode: "edit" | "read",
    viewMode: "present" | "read",
    theme: "light" | "dark" | undefined,
  ): void;
  configureTheme(config: EmbeddedPresentationConfig, theme: "light" | "dark" | undefined): void;
  createRenderer(root: HTMLElement): EmbeddedRuntimeRenderer;
  currentSessionId(): SessionId;
  initialize(): void;
  initializeTransport(transport: EmbeddedTransport): InitializedTransport;
  setConnecting(): void;
}

interface TransportRuntime {
  getSseURL: (sessionId: SessionId) => URL;
  getWsURL: (sessionId: SessionId) => URL;
}

export interface EmbeddedTransportHost {
  activateServerRequests(): void;
  prepareServer(transport: EmbeddedServerTransport): TransportRuntime;
  prepareWasm(transport: EmbeddedWasmTransport): Promise<void>;
}

interface TransportURLPatch {
  readonly getSseURL: TransportRuntime["getSseURL"];
  readonly getWsURL: TransportRuntime["getWsURL"];
}

const transportURLPatches = new WeakMap<object, TransportURLPatch>();

const configureTransportURLs = (
  runtime: TransportRuntime,
  transformTransportURL: EmbeddedServerTransport["transformTransportURL"],
): (() => void) => {
  if (transportURLPatches.has(runtime)) {
    throw new Error("The embedded runtime transport URLs already have an owner");
  }
  const originalGetWsURL = runtime.getWsURL;
  const originalGetSseURL = runtime.getSseURL;
  const getWsURL: TransportRuntime["getWsURL"] = (sessionId) =>
    transformTransportURL(originalGetWsURL.call(runtime, sessionId));
  const getSseURL: TransportRuntime["getSseURL"] = (sessionId) =>
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

export const createTransportInitializer = (
  host: EmbeddedTransportHost,
  invoke: EmbeddedFunction,
) => {
  return (transport: EmbeddedTransport): InitializedTransport => {
    let release = () => {};
    try {
      if (transport.kind === "server") {
        const runtime = host.prepareServer(transport);
        release = configureTransportURLs(runtime, transport.transformTransportURL);
        host.activateServerRequests();
        return { initialized: Promise.resolve(), release };
      }

      const workerInitialized = host.prepareWasm(transport);
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
};

export const resolveEmbeddedCellId = <Cell extends { readonly id: string }>(
  cells: readonly Cell[],
  cellId: string,
): Cell["id"] => {
  const cell = cells.find((candidate) => candidate.id === cellId);
  if (!cell) {
    throw new Error(`Cannot submit stdin for unknown cell ${JSON.stringify(cellId)}`);
  }
  return cell.id;
};

declare global {
  var __MARIMO_STUDIO_SESSION_ID__: string | undefined;
}

const exposeSession = (sessionId: SessionId, enabled: boolean): (() => void) => {
  if (!enabled) {
    return () => {};
  }
  const previous = globalThis.__MARIMO_STUDIO_SESSION_ID__;
  globalThis.__MARIMO_STUDIO_SESSION_ID__ = sessionId;
  return () => {
    if (globalThis.__MARIMO_STUDIO_SESSION_ID__ !== sessionId) {
      return;
    }
    if (previous === undefined) {
      delete globalThis.__MARIMO_STUDIO_SESSION_ID__;
    } else {
      globalThis.__MARIMO_STUDIO_SESSION_ID__ = previous;
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

export const createEmbeddedRuntimeMount = (host: EmbeddedRuntimeHost) => {
  let activeOwner: object | undefined;

  return (options: MountEmbeddedRuntimeOptions): EmbeddedRuntimeHandle => {
    if (activeOwner) {
      throw new Error("An embedded runtime is already mounted in this page");
    }
    const owner = {};
    activeOwner = owner;
    const releaseOwner = () => {
      if (activeOwner === owner) {
        activeOwner = undefined;
      }
    };

    let presentation = options.presentation;
    let initialized!: Promise<void>;
    let sessionId!: SessionId;
    let transport: InitializedTransport | undefined;
    let stopTheme = () => {};
    let stopExposingSession = () => {};
    let renderer: EmbeddedRuntimeRenderer | undefined;
    const disposers = new Set<() => void>([
      () => renderer?.dispose(),
      () => stopExposingSession(),
      () => stopTheme(),
      () => transport?.release(),
    ]);

    try {
      host.initialize();
      host.configurePresentation(
        presentation,
        options.initialMode,
        options.viewMode,
        options.theme.current(),
      );
      sessionId = host.currentSessionId();
      transport = host.initializeTransport(options.transport);
      initialized = transport.initialized;
      host.setConnecting();
      const syncTheme = () => host.configureTheme(presentation, options.theme.current());
      stopTheme = options.theme.subscribe(syncTheme);
      renderer = host.createRenderer(options.root);
      stopExposingSession = exposeSession(sessionId, options.exposeSession);
      renderer.render(initialized, options.render, sessionId);
    } catch (error) {
      const cleanupErrors = runDisposers(disposers);
      if (disposers.size === 0) {
        releaseOwner();
      }
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
      invoke: host.invoke,
      sessionId,
      update(next) {
        if (disposing) {
          return;
        }
        presentation = next;
        host.configurePresentation(
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
        const errors = runDisposers(disposers);
        if (disposers.size === 0) {
          releaseOwner();
        }
        throwDisposalErrors(errors);
      },
    };
  };
};
