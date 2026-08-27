import type { ViewNavigationIntent } from "@marimo-studio/protocol/preview-messages";

export type ViewLanding = "build" | "preserve" | "authoring";
export type ViewSelectionOwner = "browser" | "agent";

export interface StagedViewTransition {
  ready: Promise<boolean>;
  commit?(): void;
  rollback(): void | Promise<void>;
}

export interface ViewTransitionHooks {
  prepare(
    view: string,
    changed: boolean,
    navigation?: ViewNavigationIntent,
    signal?: AbortSignal,
  ): Promise<boolean>;
  stage?(
    view: string,
    changed: boolean,
    navigation?: ViewNavigationIntent,
    signal?: AbortSignal,
    owner?: ViewSelectionOwner,
  ): StagedViewTransition;
  commit(
    view: string,
    landing: ViewLanding,
    changed: boolean,
    navigation?: ViewNavigationIntent,
  ): boolean;
  cancel(): void;
}

class OwnedStagedViewTransition {
  readonly ready: Promise<boolean>;
  private rollbackOperation: Promise<void> | undefined;
  private queuedRollback: Promise<void> | undefined;

  constructor(private readonly staged: StagedViewTransition) {
    this.ready = staged.ready;
  }

  enqueueRollback(after?: Promise<void>): Promise<void> {
    this.queuedRollback ??= after ? after.then(() => this.rollback()) : this.rollback();
    return this.queuedRollback;
  }

  commit(): void {
    this.staged.commit?.();
  }

  private rollback(): Promise<void> {
    if (!this.rollbackOperation) {
      try {
        this.rollbackOperation = Promise.resolve(this.staged.rollback());
      } catch (error) {
        this.rollbackOperation = Promise.reject(error);
      }
    }
    return this.rollbackOperation;
  }
}

/** Flushes outgoing source before commit. Target source hydrates afterward. */
export class ViewTransition {
  private generation = 0;
  private staged: OwnedStagedViewTransition | undefined;
  private rollbackTail: Promise<void> | undefined;

  constructor(
    private current: string,
    private readonly hooks: ViewTransitionHooks,
  ) {}

  async select(
    view: string,
    landing: ViewLanding,
    navigation?: ViewNavigationIntent,
    signal?: AbortSignal,
    owner: ViewSelectionOwner = "browser",
  ): Promise<boolean> {
    signal?.throwIfAborted();
    const generation = ++this.generation;
    try {
      const rollback = this.rollbackStaged();
      if (rollback) {
        await abortable(rollback, signal);
      }
      if (generation !== this.generation) {
        return false;
      }
      const changed = view !== this.current;
      if (!changed) {
        this.hooks.cancel();
      }
      const preparation = signal
        ? this.hooks.prepare(view, changed, navigation, signal)
        : this.hooks.prepare(view, changed, navigation);
      if (!(await abortable(preparation, signal)) || generation !== this.generation) {
        return false;
      }
      const staged = signal
        ? this.hooks.stage?.(view, changed, navigation, signal, owner)
        : this.hooks.stage?.(view, changed, navigation, undefined, owner);
      const owned = staged ? new OwnedStagedViewTransition(staged) : undefined;
      this.staged = owned;
      if (owned && (!(await abortable(owned.ready, signal)) || generation !== this.generation)) {
        await this.rollback(owned);
        return false;
      }
      if (generation !== this.generation || signal?.aborted) {
        if (owned) {
          await this.rollback(owned);
        }
        return false;
      }
      if (!this.hooks.commit(view, landing, changed, navigation)) {
        if (owned) {
          await this.rollback(owned);
        }
        this.hooks.cancel();
        return false;
      }
      owned?.commit();
      this.current = view;
      this.staged = undefined;
      return true;
    } catch (error) {
      if (generation !== this.generation) {
        return false;
      }
      this.generation += 1;
      try {
        await this.rollbackStaged();
      } finally {
        this.hooks.cancel();
      }
      if (signal?.aborted) {
        return false;
      }
      throw error;
    }
  }

  cancel(): void {
    void this.close();
  }

  close(): Promise<void> | undefined {
    this.generation += 1;
    const rollback = this.rollbackStaged();
    void rollback?.catch(() => undefined);
    this.hooks.cancel();
    return rollback;
  }

  private rollbackStaged(): Promise<void> | undefined {
    const staged = this.staged;
    this.staged = undefined;
    return staged ? this.rollback(staged) : this.rollbackTail;
  }

  private rollback(staged: OwnedStagedViewTransition): Promise<void> {
    if (this.staged === staged) {
      this.staged = undefined;
    }
    const rollback = staged.enqueueRollback(this.rollbackTail);
    const tail = rollback.catch(() => undefined);
    this.rollbackTail = tail;
    void tail.then(() => {
      if (this.rollbackTail === tail) {
        this.rollbackTail = undefined;
      }
    });
    return rollback;
  }
}

const abortable = async <T>(operation: Promise<T>, signal?: AbortSignal): Promise<T> => {
  if (!signal) {
    return await operation;
  }
  signal.throwIfAborted();
  let abort = () => {};
  const aborted = new Promise<never>((_resolve, reject) => {
    abort = () => reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
    signal.addEventListener("abort", abort, { once: true });
  });
  try {
    return await Promise.race([operation, aborted]);
  } finally {
    signal.removeEventListener("abort", abort);
  }
};
