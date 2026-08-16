import type { RuntimeSession } from "@marimo-studio/runtime";

import {
  type EmbeddedFunction,
  type EmbeddedPresentationConfig,
  type EmbeddedRuntimeView,
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

export interface RuntimeMountOptions {
  id: string;
  instance: string;
  initialMode: InitialMode;
  viewMode: ViewMode;
  exposeSession: boolean;
  transport: EmbeddedTransport;
  updateQuery: (invoke: RuntimeInvoke, query: string) => Promise<void>;
  valueReader: (runtime: RuntimeReaderContext) => ValueReader;
  outputReader: (runtime: RuntimeReaderContext) => OutputReader;
}

const embeddedPresentation = (config: RuntimeConfig): EmbeddedPresentationConfig => ({
  appConfig: jsonValueSchema.parse(config.appConfig),
  configOverrides: jsonValueSchema.parse(config.configOverrides),
  userConfig: jsonValueSchema.parse(config.userConfig),
});

export const mountSharedRuntime = (
  config: RuntimeConfig,
  runtimeRoot: HTMLElement,
  options: RuntimeMountOptions,
): RuntimeSession => {
  let readValues: ValueReader | undefined;
  let readOutputs: OutputReader | undefined;
  const runtime = mountEmbeddedRuntime({
    exposeSession: options.exposeSession,
    initialMode: options.initialMode,
    presentation: embeddedPresentation(config),
    root: runtimeRoot,
    theme: pageThemeSource,
    transport: options.transport,
    viewMode: options.viewMode,
    render(embedded) {
      readValues ??= options.valueReader(embedded);
      readOutputs ??= options.outputReader(embedded);
      return (
        <RuntimeProjections readOutputs={readOutputs} readValues={readValues} runtime={embedded} />
      );
    },
  });

  return {
    id: options.id,
    sessionId: options.exposeSession ? runtime.sessionId : undefined,
    update(next) {
      if (next.runtime.id !== options.id || next.runtime.instance !== options.instance) {
        return "reload";
      }
      runtime.update(embeddedPresentation(next));
      return "applied";
    },
    updateQuery: (query) => options.updateQuery(runtime.invoke, query),
    dispose: () => runtime.dispose(),
  };
};
