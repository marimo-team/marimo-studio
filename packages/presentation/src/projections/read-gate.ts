export interface ProjectionRefreshClaim {
  readonly generation: number;
}

interface Deferred {
  readonly promise: Promise<void>;
  readonly resolve: () => void;
}

interface PauseOwner {
  readonly promise: Promise<ProjectionRefreshClaim>;
}

const deferred = (): Deferred => {
  let resolve = () => {};
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
};

const PROJECTION_REFRESH_ABORT_MESSAGE = "The presentation is refreshing.";

export const isProjectionRefreshAbort = (error: DOMException): boolean =>
  error.name === "AbortError" && error.message === PROJECTION_REFRESH_ABORT_MESSAGE;

const waitForCaller = (promise: Promise<void>, signal?: AbortSignal): Promise<void> => {
  if (!signal) {
    return promise;
  }
  if (signal.aborted) {
    return Promise.reject(signal.reason);
  }
  return new Promise<void>((resolve, reject) => {
    const abort = () => reject(signal.reason);
    signal.addEventListener("abort", abort, { once: true });
    promise.then(resolve, reject).finally(() => signal.removeEventListener("abort", abort));
  });
};

export class ProjectionReadGate {
  private generation = 0;
  private pending: Deferred | undefined;
  private active = new AbortController();
  private activeReads = 0;
  private drained: Deferred | undefined;
  private pause: PauseOwner | undefined;

  begin(): ProjectionRefreshClaim {
    this.generation += 1;
    this.pause = undefined;
    this.pending ??= deferred();
    this.active.abort(new DOMException(PROJECTION_REFRESH_ABORT_MESSAGE, "AbortError"));
    this.active = new AbortController();
    return { generation: this.generation };
  }

  async pauseAndDrain(): Promise<ProjectionRefreshClaim> {
    if (this.pause) {
      return await this.pause.promise;
    }
    this.generation += 1;
    this.pending ??= deferred();
    const claim = { generation: this.generation };
    let owner!: PauseOwner;
    const promise = (async () => {
      if (this.activeReads > 0) {
        this.drained ??= deferred();
        await this.drained.promise;
      }
      if (!this.current(claim)) {
        if (this.pending) {
          await this.pending.promise;
        }
        if (this.pause === owner) {
          this.pause = undefined;
        }
        return await this.pauseAndDrain();
      }
      return claim;
    })();
    owner = { promise };
    this.pause = owner;
    return await promise;
  }

  async pauseAndDrainCurrent(): Promise<ProjectionRefreshClaim> {
    while (true) {
      const claim = await this.pauseAndDrain();
      if (this.current(claim)) {
        return claim;
      }
    }
  }

  current(claim: ProjectionRefreshClaim): boolean {
    return claim.generation === this.generation;
  }

  complete(claim: ProjectionRefreshClaim): void {
    if (claim.generation !== this.generation) {
      return;
    }
    this.pending?.resolve();
    this.pending = undefined;
    this.pause = undefined;
    this.drained?.resolve();
    this.drained = undefined;
  }

  release(): void {
    this.generation += 1;
    this.active.abort(new DOMException("The presentation was disposed.", "AbortError"));
    this.pending?.resolve();
    this.pending = undefined;
    this.pause = undefined;
    this.drained?.resolve();
    this.drained = undefined;
  }

  async run<T>(
    caller: AbortSignal | undefined,
    operation: (signal: AbortSignal) => Promise<T>,
  ): Promise<T> {
    while (this.pending) {
      await waitForCaller(this.pending.promise, caller);
    }
    const signal = caller ? AbortSignal.any([caller, this.active.signal]) : this.active.signal;
    this.activeReads += 1;
    try {
      return await operation(signal);
    } finally {
      this.activeReads -= 1;
      if (this.activeReads === 0) {
        this.drained?.resolve();
        this.drained = undefined;
      }
    }
  }
}

export const projectionReadGate = new ProjectionReadGate();
