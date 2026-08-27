import { isProjectionRefreshAbort } from "../projections/read-gate.ts";

export const retryProjectionRefresh = async <Result>(
  signal: AbortSignal,
  operation: () => Promise<Result>,
): Promise<Result> => {
  for (;;) {
    signal.throwIfAborted();
    try {
      return await operation();
    } catch (error) {
      if (signal.aborted || !(error instanceof DOMException) || !isProjectionRefreshAbort(error)) {
        throw error;
      }
    }
  }
};
