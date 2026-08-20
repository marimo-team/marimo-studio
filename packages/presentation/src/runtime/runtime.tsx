import type { RuntimeSession } from "@marimo-studio/runtime";

import {
  type EmbeddedFunction,
  type EmbeddedPresentationConfig,
  type EmbeddedRuntimeView,
  type EmbeddedServerTransport,
  type EmbeddedTransport,
  mountEmbeddedRuntime,
} from "@marimo-studio/marimo-frontend/embedded-runtime";
import { jsonValueSchema, type RuntimeConfig } from "@marimo-studio/protocol/runtime-config";

import "./style.css";

import type { OutputReader } from "../outputs/reader";
import type { ValueReader } from "../values/reader";

import { RuntimeProjections } from "../projections/RuntimeProjections";
import { type InitialMode, pageThemeSource, type ViewMode } from "./runtime-configuration";

type RuntimeReaderContext = Pick<EmbeddedRuntimeView, "initialized" | "invoke" | "sessionId">;

export type RuntimeInvoke = EmbeddedFunction;

export const runRuntimeQuery = async (
  update: NonNullable<RuntimeMountOptions["updateQuery"]>,
  invoke: RuntimeInvoke,
  query: string,
  signal: AbortSignal,
): Promise<void> => {
  signal.throwIfAborted();
  await update(invoke, query, signal);
  signal.throwIfAborted();
};

export interface RuntimeMountOptions {
  autoInstantiate: boolean;
  id: string;
  instance: string;
  initialMode: InitialMode;
  viewMode: ViewMode;
  exposeSession: boolean;
  transport: EmbeddedTransport;
  serverTransport?: (config: RuntimeConfig) => EmbeddedServerTransport;
  updateQuery: (invoke: RuntimeInvoke, query: string) => Promise<void>;
  valueReader: (runtime: RuntimeReaderContext) => ValueReader;
  outputReader: (runtime: RuntimeReaderContext) => OutputReader;
}

const embeddedPresentation = (config: RuntimeConfig): EmbeddedPresentationConfig => ({
  appConfig: jsonValueSchema.parse(config.appConfig),
  configOverrides: jsonValueSchema.parse(config.configOverrides),
  userConfig: jsonValueSchema.parse(config.userConfig),
});

const presentationFingerprint = (presentation: EmbeddedPresentationConfig): string =>
  JSON.stringify(presentation);

export const mountSharedRuntime = (
  config: RuntimeConfig,
  runtimeRoot: HTMLElement,
  options: RuntimeMountOptions,
  mount: typeof mountEmbeddedRuntime = mountEmbeddedRuntime,
): RuntimeSession => {
  let presentation = embeddedPresentation(config);
  const revisionReads = new RuntimeRevisionReads(config.revision);
  let readValues: ValueReader | undefined;
  let readOutputs: OutputReader | undefined;
  let presentation = embeddedPresentation(config);
  let fingerprint = presentationFingerprint(presentation);
  let serverTransportFingerprint =
    options.transport.kind === "server"
      ? `${options.transport.url}\0${options.transport.serverToken}`
      : undefined;
  const runtime = mountEmbeddedRuntime({
    autoInstantiate: options.autoInstantiate,
    exposeSession: options.exposeSession,
    initialMode: options.initialMode,
    presentation,
    root: runtimeRoot,
    theme: pageThemeSource,
    transport: options.transport,
    viewMode: options.viewMode,
    render(embedded) {
      if (readValues === undefined) {
        const reader = options.valueReader(embedded);
        readValues = (request, signal) => revisionReads.read(reader, request, signal);
      }
      if (readOutputs === undefined) {
        const reader = options.outputReader(embedded);
        readOutputs = (request, signal) => revisionReads.read(reader, request, signal);
      }
      return (
        <RuntimeProjections readOutputs={readOutputs} readValues={readValues} runtime={embedded} />
      );
    },
  });

  const updateQuery = options.updateQuery;
  const session = {
    id: options.id,
    sessionId: options.exposeSession ? runtime.sessionId : undefined,
    update(next) {
      if (next.runtime.id !== options.id || next.runtime.instance !== options.instance) {
        return "reload";
      }
      const nextTransport = options.serverTransport?.(next);
      if (nextTransport) {
        const nextTransportFingerprint = `${nextTransport.url}\0${nextTransport.serverToken}`;
        if (nextTransportFingerprint !== serverTransportFingerprint) {
          runtime.updateServerTransport(nextTransport);
          serverTransportFingerprint = nextTransportFingerprint;
        }
      }
      presentation = embeddedPresentation(next);
      const nextFingerprint = presentationFingerprint(presentation);
      if (nextFingerprint !== fingerprint) {
        runtime.update(presentation);
        fingerprint = nextFingerprint;
      }
      return "applied";
    },
    dispose: () => {
      revisionReads.dispose();
      runtime.dispose();
    },
  };
  if (!updateQuery) {
    return session;
  }
  return {
    ...session,
    updateQuery: (value: string, signal: AbortSignal) =>
      runRuntimeQuery(updateQuery, runtime.invoke, value, signal),
  };
};
