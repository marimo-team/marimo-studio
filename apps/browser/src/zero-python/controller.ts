import type { RuntimeContext } from "@marimo-studio/runtime";
import type {
  PreparedPublicationRefresh,
  PreparedStateController,
} from "@marimo-team/marimo-export/prepared";

import type { ZeroPythonRuntimeDependencies } from "./composition.ts";
import type { StudioPreparedInteractions } from "./interactions.ts";
import type { ZeroPythonRuntimeData } from "./metadata.ts";
import type { StudioPreparedStateApi } from "./state-api.ts";

import { createStudioPreparedComposition } from "./composition.ts";
import { zeroPythonFailure } from "./errors.ts";
import { disposeStudioPreparedRuntime } from "./lifecycle.ts";

type RuntimeConfig = RuntimeContext["presentation"];

export class ZeroPythonRuntimeController {
  readonly #state: PreparedStateController;
  readonly #stateApi: StudioPreparedStateApi;
  readonly #interactions: StudioPreparedInteractions;
  #refresh: PreparedPublicationRefresh;
  #disposed = false;
  #disposal: Promise<void> | undefined;

  constructor(
    data: ZeroPythonRuntimeData,
    config: RuntimeConfig,
    root: HTMLElement,
    private readonly dependencies: ZeroPythonRuntimeDependencies,
  ) {
    const composition = createStudioPreparedComposition({
      root,
      context: () => ({ config, data }),
      dependencies,
      isDisposed: () => this.#disposed,
    });
    this.#state = composition.state;
    this.#interactions = composition.interactions;
    this.#stateApi = composition.stateApi;
    this.#refresh = composition.createRefresh(data, config.runtime.instance);
  }

  async start(signal: AbortSignal): Promise<void> {
    try {
      this.dependencies.setConnectionState("connecting");
      await this.#refresh.start(signal);
      await this.#interactions.updateQuery(globalThis.location.search, signal);
      this.#stateApi.install();
      this.dependencies.setConnectionState("ready");
    } catch (error) {
      if (!signal.aborted) {
        const failure = zeroPythonFailure(error);
        this.dependencies.setConnectionState("error", {
          code: failure.code,
          message: failure.message,
          hint: "Rebuild the prepared publication, then reload this view.",
        });
      }
      try {
        await this.dispose();
      } catch (cleanupError) {
        throw new AggregateError(
          [error, cleanupError],
          "Prepared runtime startup and cleanup failed.",
        );
      }
      throw error;
    }
  }

  async updateQuery(query: string, signal: AbortSignal): Promise<void> {
    await this.#interactions.updateQuery(query, signal);
  }

  dispose(): Promise<void> {
    this.#disposal ??= this.#dispose();
    return this.#disposal;
  }

  async #dispose(): Promise<void> {
    this.#disposed = true;
    await disposeStudioPreparedRuntime({
      refresh: this.#refresh,
      state: this.#state,
      stateApi: this.#stateApi,
    });
  }
}
