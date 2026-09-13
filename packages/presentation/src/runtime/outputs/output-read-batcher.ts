import type { OutputReadRequest, OutputReadResponse } from "@marimo-studio/protocol/output-read";

import type { OutputReader } from "../../outputs/reader";

interface PendingOutputRead {
  readonly request: OutputReadRequest;
  readonly resolve: (response: OutputReadResponse) => void;
  readonly reject: (cause: unknown) => void;
  readonly signal?: AbortSignal;
}

const projectionKey = (projection: OutputReadRequest["projections"][number]): string =>
  `${projection.siteId}\u0000${projection.instanceId}\u0000${projection.target}`;

const activeProjectionIdentity = (request: OutputReadRequest): string =>
  JSON.stringify(request.activeProjections.map(projectionKey).sort());

const uniqueProjections = (
  projections: OutputReadRequest["projections"],
): OutputReadRequest["projections"] => {
  const unique = new Map<string, OutputReadRequest["projections"][number]>();
  projections.forEach((projection) => unique.set(projectionKey(projection), projection));
  return [...unique.values()];
};

const callerAbortError = (): DOMException =>
  new DOMException("The output request was cancelled.", "AbortError");

const aggregateTooLarge = (response: OutputReadResponse): boolean =>
  Object.hasOwn(response.errors, "*") && response.errors["*"]?.code === "response-too-large";

const localizeLeafOverflow = (
  request: OutputReadRequest,
  response: OutputReadResponse,
): OutputReadResponse => {
  const target = request.projections[0]?.target;
  const overflow = response.errors["*"];
  if (!target || !overflow) {
    return response;
  }
  return {
    ...response,
    errors: Object.fromEntries([
      ...Object.entries(response.errors).filter(([selector]) => selector !== "*"),
      [target, overflow],
    ]),
  };
};

const mergeResponses = (
  left: OutputReadResponse,
  right: OutputReadResponse,
): OutputReadResponse => ({
  ...right,
  outputs: Object.fromEntries([...Object.entries(left.outputs), ...Object.entries(right.outputs)]),
  errors: Object.fromEntries([...Object.entries(left.errors), ...Object.entries(right.errors)]),
});

const readWithAggregateFallback = async (
  source: OutputReader,
  request: OutputReadRequest,
  signal: AbortSignal,
): Promise<OutputReadResponse> => {
  const response = await source(request, signal);
  if (!aggregateTooLarge(response)) {
    return response;
  }
  if (request.projections.length < 2) {
    return localizeLeafOverflow(request, response);
  }
  const middle = Math.ceil(request.projections.length / 2);
  const split = (projections: OutputReadRequest["projections"]): OutputReadRequest => ({
    ...request,
    projections,
  });
  const [left, right] = await Promise.all([
    readWithAggregateFallback(source, split(request.projections.slice(0, middle)), signal),
    readWithAggregateFallback(source, split(request.projections.slice(middle)), signal),
  ]);
  return mergeResponses(left, right);
};

const settleCaller = (operation: Promise<OutputReadResponse>, pending: PendingOutputRead): void => {
  const { signal } = pending;
  if (!signal) {
    operation.then(pending.resolve, pending.reject);
    return;
  }
  if (signal.aborted) {
    pending.reject(callerAbortError());
    return;
  }
  const abort = () => pending.reject(callerAbortError());
  signal.addEventListener("abort", abort, { once: true });
  operation
    .then(pending.resolve, pending.reject)
    .finally(() => signal.removeEventListener("abort", abort));
};

export const createBatchedOutputReader = (source: OutputReader): OutputReader => {
  let queue: PendingOutputRead[] = [];
  let scheduled = false;
  const flush = () => {
    scheduled = false;
    const pending = queue;
    queue = [];
    const groups = new Map<string, PendingOutputRead[]>();
    pending.forEach((item) => {
      if (item.signal?.aborted) {
        item.reject(callerAbortError());
        return;
      }
      const key = JSON.stringify([item.request.revision, activeProjectionIdentity(item.request)]);
      const group = groups.get(key) ?? [];
      group.push(item);
      groups.set(key, group);
    });
    groups.forEach((group) => {
      const first = group[0];
      if (!first) {
        return;
      }
      const request = {
        revision: first.request.revision,
        projections: uniqueProjections(group.flatMap((item) => item.request.projections)),
        activeProjections: first.request.activeProjections,
      };
      const signals = group.flatMap((item) => (item.signal ? [item.signal] : []));
      const batchController = new AbortController();
      const retireBatch = () => {
        if (signals.length === group.length && signals.every((signal) => signal.aborted)) {
          batchController.abort(callerAbortError());
        }
      };
      signals.forEach((signal) => signal.addEventListener("abort", retireBatch));
      retireBatch();
      const operation = Promise.resolve().then(() =>
        readWithAggregateFallback(source, request, batchController.signal),
      );
      const cleanup = () =>
        signals.forEach((signal) => signal.removeEventListener("abort", retireBatch));
      operation.then(cleanup, cleanup);
      group.forEach((item) => settleCaller(operation, item));
    });
  };
  return (request, signal) => {
    if (request.projections.length === 0) {
      return source(request, signal);
    }
    return new Promise((resolve, reject) => {
      const pending = { request, resolve, reject };
      queue.push(signal ? { ...pending, signal } : pending);
      if (!scheduled) {
        scheduled = true;
        queueMicrotask(flush);
      }
    });
  };
};
