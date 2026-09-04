import type {
  RuntimeStateApi,
  RuntimeStateDescription,
} from "@marimo-studio/presentation/runtime-state";
import type { ExportState } from "@marimo-team/marimo-export";
import type { PreparedStateSnapshot } from "@marimo-team/marimo-export/prepared";

import { parseJsonObject, type JsonObject } from "@marimo-studio/presentation/json";

export interface StudioPreparedStateApiSource {
  snapshot(): PreparedStateSnapshot;
  updateInputs(patch: JsonObject): Promise<void>;
}

export class StudioPreparedStateApi {
  #installed: RuntimeStateApi | undefined;
  #previous: RuntimeStateApi | undefined;

  constructor(private readonly source: StudioPreparedStateApiSource) {}

  install(): void {
    this.#previous = globalThis.marimoStudio.state;
    const api: RuntimeStateApi = Object.freeze({
      inputs: () => this.#publication().state.inputs,
      states: () => stateDescriptions(this.#publication().notebookExport.states()),
      update: (patch: Parameters<RuntimeStateApi["update"]>[0]) =>
        this.source.updateInputs(parseJsonObject(patch)),
    });
    globalThis.marimoStudio.state = api;
    this.#installed = api;
  }

  dispose(): void {
    if (globalThis.marimoStudio.state !== this.#installed) {
      return;
    }
    if (this.#previous === undefined) {
      delete globalThis.marimoStudio.state;
    } else {
      globalThis.marimoStudio.state = this.#previous;
    }
    this.#installed = undefined;
    this.#previous = undefined;
  }

  #publication() {
    const publication = this.source.snapshot().current;
    if (publication === undefined) {
      throw new Error("The prepared publication is still starting.");
    }
    return publication;
  }
}

const stateDescriptions = (states: readonly ExportState[]): readonly RuntimeStateDescription[] =>
  Object.freeze(
    states.map((state) =>
      Object.freeze({
        fingerprint: state.fingerprint,
        aliases: state.aliases,
        inputs: state.inputs,
      }),
    ),
  );
