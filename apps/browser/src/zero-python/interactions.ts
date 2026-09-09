import type { PreparedControlInput } from "@marimo-studio/presentation/prepared-projections";
import type { PreparedStateController } from "@marimo-team/marimo-export/prepared";

import { parseJsonObject, type JsonObject, type JsonValue } from "@marimo-studio/presentation/json";
import { isNotebookExportError } from "@marimo-team/marimo-export";
import {
  preparedControlInputPatch,
  resolvePreparedQuerySelection,
} from "@marimo-team/marimo-export/prepared";

export class StudioPreparedInteractions {
  #revisionInputs: JsonObject | undefined;
  #paused = false;

  constructor(
    private readonly state: PreparedStateController,
    private readonly isDisposed: () => boolean,
  ) {}

  get revisionInputs(): JsonObject | undefined {
    return this.#revisionInputs;
  }

  pause(): void {
    this.#paused = true;
    const snapshot = this.state.snapshot();
    this.#revisionInputs = snapshot.pendingInputs ?? snapshot.current?.state.inputs;
  }

  resume(): void {
    this.#paused = false;
    this.#revisionInputs = undefined;
  }

  async applyRevisionInputs(signal: AbortSignal): Promise<void> {
    if (!this.#paused || this.#revisionInputs === undefined) {
      return;
    }
    const publication = this.state.snapshot().current;
    if (publication === undefined) {
      return;
    }
    const inputNames = new Set(publication.notebookExport.inputNames);
    const retained = parseJsonObject(
      Object.fromEntries(
        Object.entries(this.#revisionInputs).filter(([name]) => inputNames.has(name)),
      ),
    );
    try {
      await this.state.updateInputs(retained, signal);
    } catch (error) {
      if (!isNotebookExportError(error) || error.code !== "state_unavailable") {
        throw error;
      }
      await this.state.updateInputs(publication.state.inputs, signal);
    }
  }

  async updateInputs(patch: JsonObject): Promise<void> {
    if (!this.#paused) {
      await this.state.updateInputs(patch);
      return;
    }
    const current = this.state.snapshot();
    const base =
      this.#revisionInputs ?? current.pendingInputs ?? current.current?.state.inputs ?? {};
    this.#revisionInputs = parseJsonObject({ ...base, ...patch });
  }

  async updateQuery(query: string, signal: AbortSignal): Promise<void> {
    signal.throwIfAborted();
    if (!this.#paused) {
      await this.state.updateQuery(query, signal);
      return;
    }
    const snapshot = this.state.snapshot();
    const publication = snapshot.transition.target ?? snapshot.current;
    if (publication === undefined) {
      return;
    }
    const selected = resolvePreparedQuerySelection(
      publication.notebookExport,
      publication.state,
      query,
    );
    if (selected !== undefined) {
      this.#revisionInputs = selected.inputs;
    }
  }

  controlInput(input: PreparedControlInput, peer: boolean): void {
    void this.#updateControlInput(input.objectId, input.value, peer).catch((error) => {
      if (!this.isDisposed()) {
        console.warn(
          peer
            ? "Prepared runtime peer control state could not be applied"
            : "Prepared runtime control state is not prepared yet",
          error,
        );
      }
    });
  }

  async #updateControlInput(objectId: string, value: JsonValue, peer: boolean): Promise<void> {
    const snapshot = this.state.snapshot();
    const publication = snapshot.transition.target ?? snapshot.current;
    const bindings = publication?.notebookExport.controlBindings;
    if (publication === undefined || bindings === undefined || !Object.hasOwn(bindings, objectId)) {
      return;
    }
    const patch = preparedControlInputPatch(
      this.#revisionInputs ?? snapshot.pendingInputs ?? publication.state.inputs,
      bindings[objectId]!,
      value,
    );
    if (patch === undefined) {
      return;
    }
    if (this.#paused) {
      await this.updateInputs(patch);
    } else if (peer) {
      try {
        await this.state.updateInputs(patch);
      } catch (error) {
        if (!isNotebookExportError(error) || error.code !== "state_unavailable") {
          throw error;
        }
      }
    } else {
      await this.state.updateInputs(patch);
    }
  }
}
