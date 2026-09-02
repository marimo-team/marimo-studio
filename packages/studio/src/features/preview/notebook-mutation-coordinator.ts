export interface MutationAcknowledgementPort {
  postMessage(message: {
    schema: 1;
    type:
      | "marimo-studio:editor-document-mutation-ready"
      | "marimo-studio:editor-document-mutation-failed";
    generation: number;
  }): void;
  close(): void;
}

interface PendingAdmission {
  readonly generation: number;
  readonly incarnation: number;
  readonly promise: Promise<NotebookMutationCompletion>;
}

export interface NotebookMutationCompletion {
  readonly complete: () => void;
  readonly owner: object;
}

interface PendingMutation {
  readonly generation: number;
  applied: boolean;
  built: boolean;
  complete?: NotebookMutationCompletion;
  reconciliationRequested: boolean;
  unchanged?: NotebookMutationCompletion;
}

export interface NotebookMutationEffects {
  gate(generation: number): Promise<NotebookMutationCompletion>;
  markCachedViewsStale(): void;
  resetActive(): void;
  saveFailed(generation: number): void;
  transactionFailed(generation: number): void;
}

export class NotebookMutationCoordinator {
  private incarnation = 0;
  private admittedGeneration = 0;
  private admission: PendingAdmission | undefined;
  private readonly completions = new Map<
    object,
    { builds: Array<() => void>; unchanged?: () => void }
  >();
  private readonly mutations: PendingMutation[] = [];

  constructor(private readonly effects: NotebookMutationEffects) {}

  get pending(): boolean {
    return this.mutations.length > 0;
  }

  admit(generation: number, acknowledgement: MutationAcknowledgementPort): void {
    const reply = (type: "ready" | "failed") => {
      acknowledgement.postMessage({
        schema: 1,
        type: `marimo-studio:editor-document-mutation-${type}`,
        generation,
      });
      acknowledgement.close();
    };
    if (generation < this.admittedGeneration) {
      reply("failed");
      return;
    }
    if (generation === this.admittedGeneration) {
      reply("ready");
      return;
    }
    const incarnation = this.incarnation;
    let admission = this.admission;
    if (
      admission &&
      (admission.incarnation !== incarnation || admission.generation !== generation)
    ) {
      reply("failed");
      return;
    }
    if (!admission) {
      if (!this.mutations.some((mutation) => mutation.generation === generation)) {
        this.mutations.push({
          generation,
          applied: false,
          built: false,
          reconciliationRequested: false,
        });
      }
      const promise = this.effects.gate(generation).then((unchanged) => {
        if (this.incarnation !== incarnation) {
          throw new DOMException("The editor document changed.", "AbortError");
        }
        const mutation = this.mutations.find((candidate) => candidate.generation === generation);
        if (mutation) {
          mutation.unchanged = unchanged;
        }
        return unchanged;
      });
      admission = { generation, incarnation, promise };
      this.admission = admission;
      void promise.then(
        () => {
          if (this.admission === admission && this.incarnation === incarnation) {
            this.admittedGeneration = generation;
            this.admission = undefined;
          }
        },
        () => {
          if (this.admission === admission) {
            this.admission = undefined;
          }
        },
      );
    }
    void admission.promise.then(
      () => reply("ready"),
      () => reply("failed"),
    );
  }

  saved(generation: number): boolean {
    const covered = this.mutations.filter((candidate) => candidate.generation <= generation);
    if (covered.every((mutation) => mutation.reconciliationRequested)) {
      return false;
    }
    for (const mutation of covered) {
      mutation.applied = true;
      mutation.reconciliationRequested = true;
    }
    this.settle();
    return true;
  }

  saveFailed(generation: number): void {
    const mutation = this.mutations.findLast((candidate) => candidate.generation <= generation);
    if (!mutation || mutation.reconciliationRequested) {
      return;
    }
    this.effects.saveFailed(generation);
  }

  transactionFailed(generation: number): void {
    const mutation = this.mutations.find((candidate) => candidate.generation === generation);
    if (!mutation || (mutation.applied && mutation.reconciliationRequested)) {
      return;
    }
    mutation.applied = false;
    this.admission = undefined;
    this.admittedGeneration = Math.max(0, generation - 1);
    this.effects.transactionFailed(generation);
  }

  transactionApplied(generation: number, changed: boolean): void {
    const mutation = this.mutations.find((candidate) => candidate.generation === generation);
    if (!mutation) {
      return;
    }
    mutation.applied = true;
    if (!changed && mutation.unchanged) {
      mutation.built = true;
      mutation.reconciliationRequested = true;
    }
    this.settle();
  }

  buildCompleted(generation: number | undefined, complete: () => void): boolean {
    if (!this.pending) {
      if (generation !== undefined) {
        return false;
      }
      complete();
      return true;
    }
    if (generation === undefined) {
      return false;
    }
    const index = this.mutations.findIndex((mutation) => mutation.generation === generation);
    if (index < 0) {
      return false;
    }
    for (const mutation of this.mutations.slice(0, index + 1)) {
      mutation.built = true;
    }
    const owner = this.mutations[index].unchanged?.owner;
    if (!owner) {
      return false;
    }
    this.mutations[index].complete = { owner, complete };
    this.settle();
    return !this.pending;
  }

  editorReloaded(): boolean {
    const hadPending = this.pending;
    this.incarnation += 1;
    this.admittedGeneration = 0;
    this.admission = undefined;
    this.mutations.length = 0;
    this.completions.clear();
    if (hadPending) {
      this.effects.markCachedViewsStale();
      this.effects.resetActive();
    }
    return hadPending;
  }

  private settle(): void {
    while (this.mutations[0]?.applied && this.mutations[0].built) {
      const settled = this.mutations.shift();
      if (settled?.complete) {
        const completion = this.completions.get(settled.complete.owner) ?? {
          builds: [],
        };
        completion.builds.push(settled.complete.complete);
        this.completions.set(settled.complete.owner, completion);
      } else if (settled?.unchanged) {
        const completion = this.completions.get(settled.unchanged.owner) ?? {
          builds: [],
        };
        completion.unchanged = settled.unchanged.complete;
        this.completions.set(settled.unchanged.owner, completion);
      }
    }
    if (!this.pending) {
      for (const completion of this.completions.values()) {
        if (completion.builds.length > 0) {
          for (const build of completion.builds) {
            build();
          }
        }
        completion.unchanged?.();
      }
      this.completions.clear();
    }
  }
}
