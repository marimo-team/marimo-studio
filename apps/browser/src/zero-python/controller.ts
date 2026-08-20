import type { RuntimeContext } from "@marimo-studio/runtime";
import type {
  PreparedPublicationRefresh,
  PreparedStateController,
} from "@marimo-team/marimo-export/prepared";

import type { ZeroPythonRuntimeDependencies } from "./composition.ts";
import type { AuthoredProjectionHosts } from "./hosts.ts";
import type { StudioPreparedInteractions } from "./interactions.ts";
import type { ZeroPythonRuntimeData } from "./metadata.ts";
import type { StudioPreparedRenderer } from "./renderer.ts";
import type { StudioRevisionSnapshot } from "./revision.ts";
import type { StudioPreparedStateApi } from "./state-api.ts";

import { createStudioPreparedComposition, presentationConfig } from "./composition.ts";
import { isZeroPythonQueryUnavailable, zeroPythonFailure } from "./errors.ts";
import { authoredProjectionHosts } from "./hosts.ts";
import { disposeStudioPreparedRuntime } from "./lifecycle.ts";
import { restoreStudioRevision, studioRevisionSnapshot } from "./revision.ts";

type RuntimeConfig = RuntimeContext["presentation"];

export class ZeroPythonRuntimeController {
  readonly #renderer: StudioPreparedRenderer;
  readonly #state: PreparedStateController;
  readonly #stateApi: StudioPreparedStateApi;
  readonly #interactions: StudioPreparedInteractions;
  readonly #newRefresh: (
    data: ZeroPythonRuntimeData,
    expectedInstance?: string,
  ) => PreparedPublicationRefresh;
  #refresh: PreparedPublicationRefresh;
  #hosts: AuthoredProjectionHosts;
  #disposed = false;
  #disposal: Promise<void> | undefined;
  #data: ZeroPythonRuntimeData;
  #config: RuntimeConfig;

  constructor(
    data: ZeroPythonRuntimeData,
    config: RuntimeConfig,
    private readonly root: HTMLElement,
    private readonly dependencies: ZeroPythonRuntimeDependencies,
    private readonly commitRuntimeInstance: RuntimeContext["commitRuntimeInstance"],
  ) {
    this.#data = data;
    this.#config = config;
    this.#hosts = authoredProjectionHosts(root);
    const composition = createStudioPreparedComposition({
      commitInstance: (instance) => this.#commitInstance(instance),
      root,
      context: () => ({ config: this.#config, data: this.#data, hosts: this.#hosts }),
      dependencies,
      isDisposed: () => this.#disposed,
    });
    this.#renderer = composition.renderer;
    this.#state = composition.state;
    this.#interactions = composition.interactions;
    this.#stateApi = composition.stateApi;
    this.#newRefresh = composition.createRefresh;
    this.#refresh = this.#newRefresh(data, config.runtime.instance);
  }

  async start(signal: AbortSignal): Promise<void> {
    try {
      this.dependencies.setConnectionState("connecting");
      await this.#refresh.start(signal);
      try {
        await this.#interactions.updateQuery(globalThis.location.search, signal);
      } catch (error) {
        if (!isZeroPythonQueryUnavailable(error)) {
          throw error;
        }
      }
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
          "Zero-Python runtime startup and cleanup failed.",
        );
      }
      throw error;
    }
  }

  async updateQuery(query: string, signal: AbortSignal): Promise<void> {
    await this.#interactions.updateQuery(query, signal);
  }

  async beginRevision(signal: AbortSignal) {
    signal.throwIfAborted();
    this.#interactions.pause();
    let previous: StudioRevisionSnapshot;
    try {
      this.#state.cancel(new DOMException("Zero-Python revision started", "AbortError"));
      await this.#state.settle();
      await this.#refresh.dispose();
      signal.throwIfAborted();
      previous = this.#snapshotRevision();
    } catch (error) {
      this.#interactions.resume();
      this.#refresh = this.#newRefresh(this.#data, this.#publicationInstance());
      this.#refresh.syncPolling();
      throw error;
    }
    let applied = false;
    let settled = false;
    return {
      apply: async (config: RuntimeConfig, data: ZeroPythonRuntimeData): Promise<"applied"> => {
        signal.throwIfAborted();
        if (settled) {
          throw new Error("The Zero-Python runtime revision is already settled.");
        }
        if (applied) {
          throw new Error("The Zero-Python runtime revision is already applied.");
        }
        applied = true;
        this.#config = config;
        this.#data = data;
        this.#hosts = authoredProjectionHosts(this.root);
        this.#renderer.update(presentationConfig(config));
        this.#refresh = this.#newRefresh(this.#data, config.runtime.instance);
        await this.#refresh.refresh(signal);
        await this.#interactions.applyRevisionInputs(signal);
        return "applied";
      },
      commit: async () => {
        if (settled) return;
        settled = true;
        this.#interactions.resume();
        previous.renderer.dispose();
        if (this.#refresh === previous.refresh) {
          this.#refresh = this.#newRefresh(this.#data, this.#publicationInstance());
        }
        this.#refresh.syncPolling();
      },
      rollback: async () => {
        if (settled) return;
        settled = true;
        try {
          await this.#restoreRevision(previous);
        } finally {
          this.#interactions.resume();
        }
      },
    };
  }

  dispose(): Promise<void> {
    this.#disposal ??= this.#dispose();
    return this.#disposal;
  }

  async #restoreRevision(previous: StudioRevisionSnapshot): Promise<void> {
    this.#refresh = await restoreStudioRevision({
      currentRefresh: this.#refresh,
      createRefresh: this.#newRefresh,
      previous,
      restoreContext: () => {
        this.#config = previous.config;
        this.#data = previous.data;
        this.#hosts = previous.hosts;
        this.#renderer.update(presentationConfig(previous.config));
      },
      state: this.#state,
    });
  }

  #snapshotRevision(): StudioRevisionSnapshot {
    return studioRevisionSnapshot({
      config: this.#config,
      data: this.#data,
      hosts: this.#hosts,
      state: this.#state.snapshot(),
      renderer: this.#renderer.checkpoint(),
      refresh: this.#refresh,
    });
  }

  #publicationInstance(): string {
    return this.#state.snapshot().current?.manifest.instance ?? this.#config.runtime.instance;
  }

  #commitInstance(instance: string): void {
    if (this.#config.runtime.instance === instance) {
      return;
    }
    this.#config = {
      ...this.#config,
      runtime: { ...this.#config.runtime, instance },
    };
    this.commitRuntimeInstance(instance);
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
