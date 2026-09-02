const callerAbortError = (): DOMException =>
  new DOMException("The projection request was cancelled.", "AbortError");

const waitForCaller = <Result>(
  operation: Promise<Result>,
  signal?: AbortSignal,
): Promise<Result> => {
  if (!signal) {
    return operation;
  }
  if (signal.aborted) {
    return Promise.reject(callerAbortError());
  }
  return new Promise<Result>((resolve, reject) => {
    const abort = () => reject(callerAbortError());
    signal.addEventListener("abort", abort, { once: true });
    operation.then(resolve, reject).finally(() => signal.removeEventListener("abort", abort));
  });
};

// Kernel projection resources are keyed by target. A real read may replace the
// resource while convergence releases targets that no longer have a host.
export interface ProjectionOwnershipRequest {
  readonly revision: string;
  readonly projections: { readonly target: string }[];
  readonly activeProjections: { readonly target: string }[];
}

export type ProjectionOwnershipReader<Request extends ProjectionOwnershipRequest, Response> = (
  request: Request,
  signal?: AbortSignal,
) => Promise<Response>;

export type ConvergenceProjectionSelector<Request extends ProjectionOwnershipRequest> = (
  request: Request,
  knownTargets: ReadonlySet<string>,
) => Request["projections"];

const activeTargets = (request: ProjectionOwnershipRequest): string =>
  JSON.stringify(request.activeProjections.map((projection) => projection.target).sort());

export class ProjectionOwnerReconciler<Request extends ProjectionOwnershipRequest, Response> {
  private appliedActiveTargets: string | undefined;
  private blocked = false;
  private convergenceQueued = false;
  private desired: Request | undefined;
  private desiredGeneration = 0;
  private epoch = 0;
  private readonly knownTargets = new Set<string>();
  private ownershipDirty = false;
  private projectionRevision: string | undefined;
  private retryTimer: ReturnType<typeof setTimeout> | undefined;
  private sourceAbort = new AbortController();
  private tail: Promise<void> = Promise.resolve();

  constructor(
    private readonly source: ProjectionOwnershipReader<Request, Response>,
    private readonly retryDelay = 1_000,
    private readonly transientFailure: (error: Error) => boolean = () => false,
    private readonly convergenceProjections: ConvergenceProjectionSelector<Request> = (
      request,
      knownTargets,
    ) => request.activeProjections.filter((projection) => knownTargets.has(projection.target)),
    private readonly cancelDispatchedWork = false,
  ) {}

  read(projectionRevision: string, request: Request, signal?: AbortSignal): Promise<Response> {
    if (signal?.aborted) {
      return Promise.reject(callerAbortError());
    }
    this.enterProjectionRevision(projectionRevision);
    if (this.desired && this.desired.revision !== request.revision) {
      this.desired = { ...this.desired, revision: request.revision };
      this.desiredGeneration += 1;
    }
    const operation = this.enqueue(request, this.epoch, signal);
    return waitForCaller(operation, signal);
  }

  update(projectionRevision: string, request: Request): void {
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

  private enqueue(request: Request, epoch: number, callerSignal?: AbortSignal): Promise<Response> {
    const signal = this.sourceAbort.signal;
    const operation = this.tail.then(() => {
      if (callerSignal?.aborted) {
        throw callerAbortError();
      }
      if (epoch !== this.epoch || signal.aborted) {
        throw signal.reason ?? callerAbortError();
      }
      request.projections.forEach((projection) => this.knownTargets.add(projection.target));
      this.ownershipDirty = true;
      this.scheduleConvergence();
      const sourceSignal =
        this.cancelDispatchedWork && callerSignal
          ? AbortSignal.any([signal, callerSignal])
          : signal;
      sourceSignal.throwIfAborted();
      return this.source(request, sourceSignal);
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
      // SAFETY: The spread preserves every request field, and the configured
      // selector returns the projection-list member of this same request type.
      const request = {
        ...desired,
        projections: this.convergenceProjections(desired, this.knownTargets),
      } as Request;
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
        if (!(error instanceof Error) || !this.transientFailure(error)) {
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
