import { type ErrorResponse, parseErrorResponse } from "@marimo-studio/protocol/errors";

export type EditorQuerySyncResult = "accepted" | "retry";

/** The server refused this query, so sending it again fails the same way. */
export class QuerySyncRejectedError extends Error {
  constructor(
    message: string,
    readonly hint: string | undefined,
  ) {
    super(message);
    this.name = "QuerySyncRejectedError";
  }
}

const ATTEMPT_TIMEOUT_MS = 3_000;

export const syncEditorQuery = async (
  queryUrl: string,
  serverToken: string,
  clientId: string,
  query: string,
  operationId: string,
  writeGeneration: number,
  signal?: AbortSignal,
): Promise<EditorQuerySyncResult> => {
  signal?.throwIfAborted();
  const request = new AbortController();
  const cancel = () => request.abort(signal?.reason);
  signal?.addEventListener("abort", cancel, { once: true });
  const timeout = setTimeout(() => request.abort(), ATTEMPT_TIMEOUT_MS);
  let receivedResponse = false;
  try {
    const response = await fetch(queryUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Marimo-Server-Token": serverToken,
      },
      body: JSON.stringify({ clientId, operationId, query, writeGeneration }),
      signal: request.signal,
    });
    receivedResponse = true;
    signal?.throwIfAborted();
    if (response.ok) {
      await response.arrayBuffer();
      signal?.throwIfAborted();
      request.signal.throwIfAborted();
      return "accepted";
    }
    if (response.status === 408 || response.status === 429 || response.status >= 500) {
      return "retry";
    }
    const detail = await errorDetail(response);
    signal?.throwIfAborted();
    request.signal.throwIfAborted();
    if (response.status === 409 && detail.transient === true) {
      return "retry";
    }
    throw new QuerySyncRejectedError(
      detail.message ?? "The Studio server refused the query state.",
      detail.hint,
    );
  } catch (error) {
    if (signal?.aborted) {
      throw error;
    }
    if (request.signal.aborted || !receivedResponse) {
      return "retry";
    }
    throw error;
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", cancel);
  }
};

const errorDetail = async (response: Response): Promise<ErrorResponse> => {
  try {
    return parseErrorResponse(await response.json());
  } catch {
    return {};
  }
};
