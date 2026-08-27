import type { OutputReadRequest, OutputReadResponse } from "@marimo-studio/protocol/output-read";

import type { OutputReader } from "../../outputs/reader";

import {
  outputCallerAbortError,
  OutputRequestError,
  waitForOutputCaller,
} from "../../outputs/remote";

// Kernel output ownership is keyed by target. A real read replaces the owner
// when its source site or mounted instance changes.
const activeTargets = (request: OutputReadRequest): string =>
  JSON.stringify(request.activeProjections.map((projection) => projection.target).sort());

export class OutputOwnerReconciler {
  private appliedActiveTargets: string | undefined;
  private blocked = false;
  private convergenceQueued = false;
  private desired: OutputReadRequest | undefined;
  private desiredGeneration = 0;
  private epoch = 0;
  private readonly knownTargets = new Set<string>();
  private ownershipDirty = false;
  private projectionRevision: string | undefined;
  private retryTimer: ReturnType<typeof setTimeout> | undefined;
  private sourceAbort = new AbortController();
  private tail: Promise<void> = Promise.resolve();

  constructor(
    private readonly source: OutputReader,
    private readonly retryDelay = 1_000,
  ) {}

  read(
    projectionRevision: string,
    request: Parameters<OutputReader>[0],
    signal?: AbortSignal,
  ): ReturnType<OutputReader> {
    if (signal?.aborted) {
      return Promise.reject(outputCallerAbortError());
    }
    this.enterProjectionRevision(projectionRevision);
    if (this.desired && this.desired.revision !== request.revision) {
      this.desired = { ...this.desired, revision: request.revision };
      this.desiredGeneration += 1;
    }
    const operation = this.enqueue(request, this.epoch, signal);
    return waitForOutputCaller(operation, signal);
  }

  update(projectionRevision: string, request: OutputReadRequest): void {
    this.enterProjectionRevision(projectionRevision);
    this.desired = request;
    this.desiredGeneration += 1;
    this.blocked = false;
    if (this.retryTimer !== undefined) {
      clearTimeout(this.retryTimer);
      this.retryTimer = undefined;
    }
    this.scheduleConvergence();
  }

  pause(): void {
    this.epoch += 1;
    this.sourceAbort.abort();
    this.sourceAbort = new AbortController();
    this.appliedActiveTargets = undefined;
    this.blocked = false;
    this.desired = undefined;
    this.desiredGeneration = 0;
    this.knownTargets.clear();
    this.ownershipDirty = false;
    this.projectionRevision = undefined;
    if (this.retryTimer !== undefined) {
      clearTimeout(this.retryTimer);
      this.retryTimer = undefined;
    }
  }

  dispose(): void {
    this.pause();
  }

  private enqueue(
    request: OutputReadRequest,
    epoch: number,
    callerSignal?: AbortSignal,
  ): Promise<OutputReadResponse> {
    const signal = this.sourceAbort.signal;
    const operation = this.tail.then(() => {
      if (callerSignal?.aborted) {
        throw outputCallerAbortError();
      }
      if (epoch !== this.epoch || signal.aborted) {
        throw signal.reason ?? outputCallerAbortError();
      }
      request.projections.forEach((projection) => this.knownTargets.add(projection.target));
      this.ownershipDirty = true;
      this.scheduleConvergence();
      return this.source(request, signal);
    });
    this.tail = operation.then(
      () => {
        if (epoch === this.epoch) {
          this.appliedActiveTargets = activeTargets(request);
          this.blocked = false;
          this.ownershipDirty = false;
          this.scheduleConvergence();
        }
      },
      () => {},
    );
    return operation;
  }

  private scheduleConvergence(): void {
    if (
      this.blocked ||
      this.convergenceQueued ||
      this.retryTimer !== undefined ||
      this.desired === undefined ||
      (!this.ownershipDirty &&
        (this.appliedActiveTargets === undefined ||
          this.appliedActiveTargets === activeTargets(this.desired)))
    ) {
      return;
    }
    const epoch = this.epoch;
    this.convergenceQueued = true;
    const convergence = this.tail.then(() => this.converge(epoch));
    this.tail = convergence.then(
      () => this.finishConvergence(),
      () => this.finishConvergence(),
    );
  }

  private async converge(epoch: number): Promise<void> {
    while (epoch === this.epoch) {
      const desired = this.desired;
      if (
        desired === undefined ||
        (!this.ownershipDirty &&
          (this.appliedActiveTargets === undefined ||
            this.appliedActiveTargets === activeTargets(desired)))
      ) {
        return;
      }
      const request = {
        ...desired,
        projections: desired.activeProjections.filter((projection) =>
          this.knownTargets.has(projection.target),
        ),
      };
      const generation = this.desiredGeneration;
      const signal = this.sourceAbort.signal;
      this.ownershipDirty = true;
      try {
        await this.source(request, signal);
      } catch (error) {
        if (epoch !== this.epoch) {
          return;
        }
        if (generation !== this.desiredGeneration) {
          continue;
        }
        if (!(error instanceof OutputRequestError) || !error.transient) {
          this.blocked = true;
          return;
        }
        this.scheduleRetry(epoch, generation);
        return;
      }
      if (epoch === this.epoch) {
        this.appliedActiveTargets = activeTargets(request);
        this.ownershipDirty = false;
      }
    }
  }

  private finishConvergence(): void {
    this.convergenceQueued = false;
    this.scheduleConvergence();
  }

  private scheduleRetry(epoch: number, generation: number): void {
    if (epoch !== this.epoch || generation !== this.desiredGeneration) {
      return;
    }
    this.retryTimer ??= setTimeout(() => {
      this.retryTimer = undefined;
      if (epoch === this.epoch) {
        this.scheduleConvergence();
      }
    }, this.retryDelay);
  }

  private enterProjectionRevision(projectionRevision: string): void {
    if (this.projectionRevision === undefined) {
      this.projectionRevision = projectionRevision;
      return;
    }
    if (this.projectionRevision === projectionRevision) {
      return;
    }
    // Presentation revisions advance the wire identity in `desired`. Only a
    // projection revision replaces kernel ownership and aborts outstanding work.
    const owned = this.appliedActiveTargets !== undefined || this.ownershipDirty;
    this.pause();
    this.projectionRevision = projectionRevision;
    this.ownershipDirty = owned;
  }
}
