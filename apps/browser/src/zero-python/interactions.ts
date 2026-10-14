import type { JsonObject, JsonValue } from "@marimo-studio/presentation/json";
import type { PreparedControlInput } from "@marimo-studio/presentation/prepared-projections";
import type { PreparedStateController } from "@marimo-team/marimo-export/prepared";

import { isNotebookExportError } from "@marimo-team/marimo-export";
import { preparedControlInputPatch } from "@marimo-team/marimo-export/prepared";

export class StudioPreparedInteractions {
  constructor(
    private readonly state: PreparedStateController,
    private readonly isDisposed: () => boolean,
  ) {}

  async updateInputs(patch: JsonObject): Promise<void> {
    await this.state.updateInputs(patch);
  }

  async updateQuery(query: string, signal: AbortSignal): Promise<void> {
    signal.throwIfAborted();
    await this.state.updateQuery(query, signal);
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
      snapshot.pendingInputs ?? publication.state.inputs,
      bindings[objectId]!,
      value,
    );
    if (patch === undefined) {
      return;
    }
    if (!peer) {
      await this.state.updateInputs(patch);
      return;
    }
    try {
      await this.state.updateInputs(patch);
    } catch (error) {
      if (!isNotebookExportError(error) || error.code !== "state_unavailable") {
        throw error;
      }
    }
  }
}
