import type { ProjectedOutputFunctionTransition } from "@marimo-studio/marimo-frontend/projected-output-function-gate";

import type { ProjectionRefreshClaim } from "../projections/read-gate.ts";

interface ProjectionTransitions {
  begin(): ProjectionRefreshClaim;
  complete(claim: ProjectionRefreshClaim): void;
  pauseAndDrainCurrent(signal?: AbortSignal): Promise<ProjectionRefreshClaim>;
}

interface FunctionTransitions {
  begin(): ProjectedOutputFunctionTransition | undefined;
  cancel(claim: ProjectedOutputFunctionTransition | undefined): void;
  complete(claim: ProjectedOutputFunctionTransition | undefined): void;
}

export interface ExternalRefreshLease {
  readonly drained: Promise<void>;
  release(): void;
}

interface ExternalRefreshOwner {
  drained: boolean;
  readonly reject: (cause: DOMException) => void;
}

export class ExternalRefreshGate {
  private readonly owners = new Map<symbol, ExternalRefreshOwner>();
  private functionClaim: ProjectedOutputFunctionTransition | undefined;
  private projectionClaim: ProjectionRefreshClaim | undefined;
  private projectionDrain: Promise<void> = Promise.resolve();
  private projectionDrainController: AbortController | undefined;
  private projectionOperation: symbol | undefined;

  constructor(
    private readonly projections: ProjectionTransitions,
    private readonly functions: FunctionTransitions,
  ) {}

  acquire(mode: "refresh" | "mutation"): ExternalRefreshLease {
    const owner = Symbol("external-refresh-owner");
    const first = this.owners.size === 0;
    let rejectOwner = (_cause: DOMException) => {};
    const ownerCancelled = new Promise<void>((_resolve, reject) => {
      rejectOwner = reject;
    });
    const state = { drained: false, reject: rejectOwner };
    this.owners.set(owner, state);
    if (first) {
      this.start(mode);
    } else if (mode === "mutation") {
      this.beginProjectionDrain();
    }
    const functionDrain = this.functionClaim?.drained ?? Promise.resolve();
    let active = true;
    const drained = Promise.race([
      Promise.all([this.projectionDrain, functionDrain]).then(() => undefined),
      ownerCancelled,
    ]).then(() => {
      if (this.owners.get(owner) === state) {
        state.drained = true;
      }
    });
    if (mode === "refresh") {
      void drained.catch(() => {});
    }
    return {
      drained,
      release: () => {
        if (!active) {
          return;
        }
        active = false;
        this.release(owner, state);
      },
    };
  }

  presentationChanged(): void {
    this.rejectUndrained("The presentation changed before the document mutation paused.");
    this.finish(false);
  }

  cancel(): void {
    this.rejectUndrained("The presentation closed before the document mutation paused.");
    this.finish(true);
  }

  private start(mode: "refresh" | "mutation"): void {
    this.functionClaim = this.functions.begin();
    if (mode === "refresh") {
      this.projectionClaim = this.projections.begin();
      this.projectionDrain = Promise.resolve();
      return;
    }
    this.beginProjectionDrain();
  }

  private beginProjectionDrain(): void {
    if (this.projectionDrainController) {
      return;
    }
    const controller = new AbortController();
    const operation = Symbol("external-projection-drain");
    this.projectionDrainController = controller;
    this.projectionOperation = operation;
    this.projectionDrain = this.projections.pauseAndDrainCurrent(controller.signal).then(
      (claim) => {
        if (this.projectionOperation !== operation || this.owners.size === 0) {
          this.projections.complete(claim);
          return;
        }
        this.projectionClaim = claim;
      },
      (error: Error) => {
        if (!controller.signal.aborted) {
          throw error;
        }
      },
    );
  }

  private rejectUndrained(message: string): void {
    for (const owner of this.owners.values()) {
      if (!owner.drained) {
        owner.reject(new DOMException(message, "AbortError"));
      }
    }
  }

  private release(owner: symbol, state: ExternalRefreshOwner): void {
    if (this.owners.get(owner) !== state) {
      return;
    }
    this.owners.delete(owner);
    if (this.owners.size === 0) {
      this.finish(false);
    }
  }

  private finish(cancelFunctions: boolean): void {
    this.owners.clear();
    this.projectionOperation = undefined;
    this.projectionDrainController?.abort(
      new DOMException("The external presentation refresh ended.", "AbortError"),
    );
    this.projectionDrainController = undefined;
    if (this.projectionClaim) {
      this.projections.complete(this.projectionClaim);
      this.projectionClaim = undefined;
    }
    if (cancelFunctions) {
      this.functions.cancel(this.functionClaim);
    } else {
      this.functions.complete(this.functionClaim);
    }
    this.functionClaim = undefined;
    this.projectionDrain = Promise.resolve();
  }
}
