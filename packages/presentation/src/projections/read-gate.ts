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

const waitForCaller = <Result>(promise: Promise<Result>, signal?: AbortSignal): Promise<Result> => {
  if (!signal) {
    return promise;
  }
  if (signal.aborted) {
    return Promise.reject(signal.reason);
  }
  return new Promise<Result>((resolve, reject) => {
    const cleanup = () => signal.removeEventListener("abort", abort);
    const abort = () => {
      cleanup();
      reject(signal.reason);
    };
    signal.addEventListener("abort", abort, { once: true });
    promise.then(
      (result) => {
        cleanup();
        resolve(result);
      },
      (error) => {
        cleanup();
        reject(error);
      },
    );
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

  async pauseAndDrain(signal?: AbortSignal): Promise<ProjectionRefreshClaim> {
    if (signal?.aborted) {
      throw signal.reason;
    }
    if (this.pause) {
      return await waitForCaller(this.pause.promise, signal);
    }
    this.generation += 1;
    this.pending ??= deferred();
    const claim = { generation: this.generation };
    let owner!: PauseOwner;
    const promise = (async () => {
      try {
        if (this.activeReads > 0) {
          this.drained ??= deferred();
          await waitForCaller(this.drained.promise, signal);
        }
        if (!this.current(claim)) {
          if (this.pending) {
            await waitForCaller(this.pending.promise, signal);
          }
          if (this.pause === owner) {
            this.pause = undefined;
          }
          return await this.pauseAndDrain(signal);
        }
        return claim;
      } catch (error) {
        if (this.current(claim)) {
          this.complete(claim);
        }
        throw error;
      }
    })();
    owner = { promise };
    this.pause = owner;
    return await promise;
  }

  async pauseAndDrainCurrent(signal?: AbortSignal): Promise<ProjectionRefreshClaim> {
    while (true) {
      const claim = await this.pauseAndDrain(signal);
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
