export interface PreparedModelGraphSnapshot<Record> {
  readonly files: Readonly<{ [path: string]: string }>;
  readonly records: ReadonlyMap<string, Record>;
}

declare const preparedModelGraphCheckpoint: unique symbol;

export interface PreparedModelGraphCheckpoint<Record> {
  readonly [preparedModelGraphCheckpoint]: Record;
}

export interface PreparedModelGraphPort<Record, LiveState> {
  id(record: Record): string;
  active(record: Record): boolean;
  same(left: Record, right: Record): boolean;
  changesModule(previous: Record, next: Record): boolean;
  capture(id: string): LiveState;
  merge(record: Record, state: LiveState): Record;
  replay(records: readonly Record[], signal?: AbortSignal): Promise<void>;
  restore(id: string, state: LiveState): void | Promise<void>;
  close(id: string): Promise<void>;
  setFiles(files: Readonly<{ [path: string]: string }>): void;
  validate?(record: Record, signal?: AbortSignal): Promise<void>;
  preflight?(record: Record, signal?: AbortSignal): Promise<void>;
}

const abortReason = (signal: AbortSignal, message: string): Error =>
  signal.reason instanceof Error ? signal.reason : new DOMException(message, "AbortError");

export interface PreparedModelGraphReplacement<Record> {
  readonly mutated: boolean;
  readonly remount: boolean;
  commit(): Promise<PreparedModelGraphSnapshot<Record> | undefined>;
  rollback(): Promise<void>;
}

export class PreparedModelGraphReplacementError extends Error {
  readonly remount = true;

  constructor(cause: Error) {
    super("Prepared Marimo model graph replacement requires a full remount", { cause });
    this.name = "PreparedModelGraphReplacementError";
  }
}

interface GraphChanges<Record> {
  readonly additions: readonly Record[];
  readonly stableUpdates: readonly Record[];
  readonly replacements: readonly Record[];
  readonly removals: readonly Record[];
}

interface LiveGraphState<LiveState> {
  readonly stable: ReadonlyMap<string, LiveState>;
  readonly replacements: ReadonlyMap<string, LiveState>;
  readonly removals: ReadonlyMap<string, LiveState>;
}

const emptyGraph = <Record>(): PreparedModelGraphSnapshot<Record> => ({
  files: Object.freeze({}),
  records: new Map(),
});

const graphFailure = (cause: unknown): Error =>
  cause instanceof Error ? cause : new Error(String(cause));

const sameFiles = (
  left: Readonly<Record<string, string>>,
  right: Readonly<Record<string, string>>,
): boolean => {
  const leftNames = Object.keys(left);
  const rightNames = Object.keys(right);
  return (
    leftNames.length === rightNames.length &&
    leftNames.every((name) => Object.hasOwn(right, name) && left[name] === right[name])
  );
};

const snapshotCopy = <Record>(
  snapshot: PreparedModelGraphSnapshot<Record>,
  port: PreparedModelGraphPort<Record, unknown>,
): PreparedModelGraphSnapshot<Record> => {
  const records = new Map<string, Record>();
  snapshot.records.forEach((record, key) => {
    const id = port.id(record);
    if (id !== key) {
      throw new Error(
        `Prepared Marimo model graph record ${JSON.stringify(key)} has identity ${JSON.stringify(id)}`,
      );
    }
    records.set(id, record);
  });
  return Object.freeze({
    files: Object.freeze({ ...snapshot.files }),
    records,
  });
};

const changesFor = <Record, LiveState>(
  previous: PreparedModelGraphSnapshot<Record>,
  next: PreparedModelGraphSnapshot<Record>,
  port: PreparedModelGraphPort<Record, LiveState>,
): GraphChanges<Record> => {
  const additions: Record[] = [];
  const stableUpdates: Record[] = [];
  const replacements: Record[] = [];
  next.records.forEach((record, id) => {
    if (!port.active(record)) return;
    const current = previous.records.get(id);
    if (current === undefined || !port.active(current)) {
      additions.push(record);
      return;
    }
    if (port.same(current, record)) return;
    if (port.changesModule(current, record)) replacements.push(record);
    else stableUpdates.push(record);
  });
  return { additions, stableUpdates, replacements, removals: [] };
};

const currentRecordActive = <Record, LiveState>(
  next: PreparedModelGraphSnapshot<Record>,
  id: string,
  port: PreparedModelGraphPort<Record, LiveState>,
): boolean => {
  const record = next.records.get(id);
  return record !== undefined && port.active(record);
};

const plannedChanges = <Record, LiveState>(
  previous: PreparedModelGraphSnapshot<Record>,
  next: PreparedModelGraphSnapshot<Record>,
  port: PreparedModelGraphPort<Record, LiveState>,
): GraphChanges<Record> => {
  const changes = changesFor(previous, next, port);
  return {
    ...changes,
    removals: [...previous.records.entries()]
      .filter(([id, record]) => port.active(record) && !currentRecordActive(next, id, port))
      .map(([, record]) => record),
  };
};

const captureStates = <Record, LiveState>(
  changes: GraphChanges<Record>,
  port: PreparedModelGraphPort<Record, LiveState>,
): LiveGraphState<LiveState> => {
  const capture = (records: readonly Record[]): Map<string, LiveState> =>
    new Map(records.map((record) => [port.id(record), port.capture(port.id(record))]));
  return {
    stable: capture(changes.stableUpdates),
    replacements: capture(changes.replacements),
    removals: capture(changes.removals),
  };
};

const attempt = async (errors: Error[], action: () => void | Promise<void>): Promise<void> => {
  try {
    await action();
  } catch (error) {
    errors.push(graphFailure(error));
  }
};

const eachSequential = async <Value>(
  values: Iterable<Value>,
  action: (value: Value) => void | Promise<void>,
): Promise<void> => {
  for (const value of values) {
    // Model teardown and replay share registry identities, so order is part of the lifecycle.
    await action(value);
  }
};

const throwCleanup = (errors: readonly Error[], message: string): void => {
  if (errors.length === 1) throw errors[0];
  if (errors.length > 1) throw new AggregateError(errors, message);
};

const settledReplacement = <Record>(
  mutated: boolean,
  remount: boolean,
  settle: (
    commit: boolean,
  ) =>
    | PreparedModelGraphSnapshot<Record>
    | undefined
    | Promise<PreparedModelGraphSnapshot<Record> | undefined>,
): PreparedModelGraphReplacement<Record> => {
  let committed = false;
  let commitFailure: Error | undefined;
  let commitTask: Promise<PreparedModelGraphSnapshot<Record> | undefined> | undefined;
  let rollbackTask: Promise<void> | undefined;
  return Object.freeze({
    mutated,
    remount,
    commit() {
      if (rollbackTask !== undefined) return rollbackTask.then(() => undefined);
      commitTask ??= Promise.resolve()
        .then(() => settle(true))
        .then((result) => {
          committed = true;
          return result;
        })
        .catch((cause: unknown) => {
          commitFailure = graphFailure(cause);
          throw cause;
        });
      return commitTask;
    },
    rollback() {
      rollbackTask ??= (commitTask ?? Promise.resolve())
        .catch(() => {})
        .then(async () => {
          if (committed) return;
          try {
            await settle(false);
          } catch (error) {
            throw new PreparedModelGraphReplacementError(
              commitFailure === undefined
                ? graphFailure(error)
                : new AggregateError(
                    [commitFailure, graphFailure(error)],
                    "Prepared Marimo model graph commit and rollback failed",
                  ),
            );
          }
        });
      return rollbackTask;
    },
  });
};

export class PreparedModelGraph<Record, LiveState> {
  readonly #checkpoints = new WeakMap<
    object,
    {
      readonly source: PreparedModelGraphSnapshot<Record>;
      readonly snapshot: PreparedModelGraphSnapshot<Record>;
    }
  >();
  readonly #port: PreparedModelGraphPort<Record, LiveState>;
  #current: PreparedModelGraphSnapshot<Record>;
  #active: AbortController | undefined;
  #operation: Promise<PreparedModelGraphReplacement<Record>> | undefined;
  #pending: PreparedModelGraphReplacement<Record> | undefined;
  #disposed = false;
  #disposal: Promise<void> | undefined;

  constructor(
    port: PreparedModelGraphPort<Record, LiveState>,
    initial: PreparedModelGraphSnapshot<Record> = emptyGraph<Record>(),
  ) {
    this.#port = port;
    this.#current = snapshotCopy(initial, port);
    this.#port.setFiles(this.#current.files);
  }

  checkpoint(): PreparedModelGraphCheckpoint<Record> {
    this.#requireIdle();
    const records = new Map(this.#current.records);
    this.#current.records.forEach((record, id) => {
      if (this.#port.active(record)) {
        records.set(id, this.#port.merge(record, this.#port.capture(id)));
      }
    });
    const snapshot = snapshotCopy({ files: this.#current.files, records }, this.#port);
    // SAFETY: The private WeakMap registers this opaque checkpoint before it is returned.
    const checkpoint = Object.freeze({}) as PreparedModelGraphCheckpoint<Record>;
    this.#checkpoints.set(checkpoint, { snapshot, source: this.#current });
    return checkpoint;
  }

  replace(
    target: PreparedModelGraphSnapshot<Record> | PreparedModelGraphCheckpoint<Record>,
    signal?: AbortSignal,
  ): Promise<PreparedModelGraphReplacement<Record>> {
    if (signal?.aborted) {
      return Promise.reject(abortReason(signal, "Prepared Marimo model graph replacement aborted"));
    }
    if (this.#disposed) {
      return Promise.resolve(settledReplacement(false, false, () => undefined));
    }
    this.#requireIdle();
    const controller = new AbortController();
    const abort = () => {
      if (signal !== undefined) {
        controller.abort(abortReason(signal, "Prepared Marimo model graph replacement aborted"));
      }
    };
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) abort();
    this.#active = controller;
    const operation = this.#replace(target, controller.signal);
    this.#operation = operation;
    return operation.finally(() => {
      signal?.removeEventListener("abort", abort);
      if (this.#active === controller) this.#active = undefined;
      if (this.#operation === operation) this.#operation = undefined;
    });
  }

  dispose(): Promise<void> {
    this.#disposal ??= this.#dispose();
    return this.#disposal;
  }

  async #replace(
    target: PreparedModelGraphSnapshot<Record> | PreparedModelGraphCheckpoint<Record>,
    signal: AbortSignal,
  ): Promise<PreparedModelGraphReplacement<Record>> {
    const checkpoint = this.#checkpoints.get(target);
    // SAFETY: Every opaque checkpoint resolves in the private WeakMap while other values are snapshots.
    const value =
      checkpoint === undefined
        ? (target as PreparedModelGraphSnapshot<Record>)
        : checkpoint.snapshot;
    const next = snapshotCopy(value, this.#port);
    const adopt = checkpoint?.source ?? next;
    const previous = this.#current;
    const changes = plannedChanges(previous, next, this.#port);
    const mutated =
      !sameFiles(previous.files, next.files) ||
      changes.additions.length > 0 ||
      changes.stableUpdates.length > 0 ||
      changes.replacements.length > 0 ||
      changes.removals.length > 0;
    if (!mutated) {
      return this.#replacement(false, false, () => {
        this.#current = adopt;
        return adopt;
      });
    }
    return this.#stage(previous, next, adopt, changes, signal);
  }

  async #stage(
    previous: PreparedModelGraphSnapshot<Record>,
    next: PreparedModelGraphSnapshot<Record>,
    adopt: PreparedModelGraphSnapshot<Record>,
    changes: GraphChanges<Record>,
    signal: AbortSignal,
  ): Promise<PreparedModelGraphReplacement<Record>> {
    this.#port.setFiles({ ...previous.files, ...next.files });
    try {
      await this.#preflight(changes, signal);
    } catch (error) {
      this.#port.setFiles(previous.files);
      throw error;
    }
    let live: LiveGraphState<LiveState>;
    try {
      live = captureStates(changes, this.#port);
    } catch (error) {
      this.#port.setFiles(previous.files);
      throw error;
    }
    const added = new Set<string>();
    const replaced = new Set<string>();
    const removed = new Set<string>();
    const rollback = () => this.#rollback(previous, changes, live, added, replaced, removed);
    let remount = false;
    try {
      const replay = new Map<string, Record>();
      await eachSequential(changes.replacements, async (record) => {
        signal.throwIfAborted();
        const id = this.#port.id(record);
        const state = live.replacements.get(id)!;
        replaced.add(id);
        remount = true;
        await this.#port.close(id);
        replay.set(id, this.#port.merge(record, state));
      });
      changes.additions.forEach((record) => {
        const id = this.#port.id(record);
        added.add(id);
        replay.set(id, record);
      });
      changes.stableUpdates.forEach((record) => replay.set(this.#port.id(record), record));
      signal.throwIfAborted();
      const records = [...next.records.keys()].flatMap((id) => {
        const record = replay.get(id);
        return record === undefined ? [] : [record];
      });
      if (records.length > 0) await this.#port.replay(records, signal);
      signal.throwIfAborted();
    } catch (error) {
      const failure = graphFailure(error);
      try {
        await rollback();
      } catch (rollbackError) {
        throw new PreparedModelGraphReplacementError(
          new AggregateError(
            [failure, graphFailure(rollbackError)],
            "Prepared Marimo model graph replacement and rollback failed",
          ),
        );
      }
      if (remount) throw new PreparedModelGraphReplacementError(failure);
      throw failure;
    }
    return this.#replacement(true, changes.replacements.length > 0, async (commit) => {
      if (!commit) {
        await rollback();
        return undefined;
      }
      await eachSequential(changes.removals, async (record) => {
        const id = this.#port.id(record);
        removed.add(id);
        await this.#port.close(id);
      });
      this.#port.setFiles(next.files);
      this.#current = adopt;
      return adopt;
    });
  }

  async #preflight(changes: GraphChanges<Record>, signal: AbortSignal): Promise<void> {
    await eachSequential(
      [...changes.additions, ...changes.stableUpdates, ...changes.replacements],
      async (record) => {
        signal.throwIfAborted();
        await this.#port.validate?.(record, signal);
      },
    );
    await eachSequential([...changes.additions, ...changes.replacements], async (record) => {
      signal.throwIfAborted();
      await this.#port.preflight?.(record, signal);
    });
    signal.throwIfAborted();
  }

  async #rollback(
    previous: PreparedModelGraphSnapshot<Record>,
    changes: GraphChanges<Record>,
    live: LiveGraphState<LiveState>,
    added: ReadonlySet<string>,
    replaced: ReadonlySet<string>,
    removed: ReadonlySet<string>,
  ): Promise<void> {
    this.#port.setFiles(previous.files);
    const errors: Error[] = [];
    await eachSequential(added, (id) => attempt(errors, () => this.#port.close(id)));
    await eachSequential(live.stable, ([id, state]) =>
      attempt(errors, () => this.#port.restore(id, state)),
    );
    await this.#replayPrevious(
      errors,
      previous,
      new Map([...live.replacements, ...live.removals]),
      new Set([...replaced, ...removed]),
    );
    throwCleanup(errors, "Prepared Marimo model graph rollback failed");
  }

  async #replayPrevious(
    errors: Error[],
    previous: PreparedModelGraphSnapshot<Record>,
    states: ReadonlyMap<string, LiveState>,
    ids: ReadonlySet<string>,
  ): Promise<void> {
    await eachSequential(ids, (id) => attempt(errors, () => this.#port.close(id)));
    const records: Record[] = [];
    previous.records.forEach((record, id) => {
      const state = states.get(id);
      if (!ids.has(id) || state === undefined) return;
      try {
        records.push(this.#port.merge(record, state));
      } catch (error) {
        errors.push(graphFailure(error));
      }
    });
    if (records.length > 0) await attempt(errors, () => this.#port.replay(records));
  }

  #replacement(
    mutated: boolean,
    remount: boolean,
    settle: (
      commit: boolean,
    ) =>
      | PreparedModelGraphSnapshot<Record>
      | undefined
      | Promise<PreparedModelGraphSnapshot<Record> | undefined>,
  ): PreparedModelGraphReplacement<Record> {
    const replacement = settledReplacement(mutated, remount, async (commit) => {
      let settled = false;
      try {
        const result = await settle(commit);
        settled = true;
        return result;
      } finally {
        if (settled && this.#pending === replacement) this.#pending = undefined;
      }
    });
    this.#pending = replacement;
    return replacement;
  }

  #requireIdle(): void {
    if (this.#disposed) throw new Error("Prepared Marimo model graph is disposed");
    if (this.#operation !== undefined || this.#pending !== undefined) {
      throw new Error("A prepared AnyWidget graph replacement is already active");
    }
  }

  async #dispose(): Promise<void> {
    this.#disposed = true;
    this.#active?.abort(new DOMException("Prepared Marimo model graph disposed", "AbortError"));
    const errors: Error[] = [];
    if (this.#operation !== undefined) await attempt(errors, () => this.#operation?.then(() => {}));
    if (this.#pending !== undefined) await attempt(errors, () => this.#pending?.rollback());
    await eachSequential(this.#current.records, ([id, record]) =>
      this.#port.active(record) ? attempt(errors, () => this.#port.close(id)) : undefined,
    );
    await attempt(errors, () => this.#port.setFiles({}));
    this.#current = emptyGraph();
    throwCleanup(errors, "Prepared Marimo model graph disposal failed");
  }
}
