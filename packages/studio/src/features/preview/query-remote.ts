export type EditorQuerySyncResult = "accepted" | "retry";

const ATTEMPT_TIMEOUT_MS = 3_000;

export const syncEditorQuery = async (
  queryUrl: string,
  serverToken: string,
  clientId: string,
  query: string,
  operationId: string,
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
      body: JSON.stringify({ clientId, operationId, query }),
      signal: request.signal,
    });
    receivedResponse = true;
    signal?.throwIfAborted();
    if (response.ok) {
      return "accepted";
    }
    if (response.status === 408 || response.status === 429 || response.status >= 500) {
      return "retry";
    }
    if (response.status === 409) {
      const transient = await isTransient(response);
      signal?.throwIfAborted();
      request.signal.throwIfAborted();
      if (transient) {
        return "retry";
      }
    }
    throw new Error(`Query synchronization failed with ${response.status}`);
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

const isTransient = async (response: Response): Promise<boolean> => {
  try {
    const payload: unknown = await response.json();
    return (
      typeof payload === "object" &&
      payload !== null &&
      "transient" in payload &&
      payload.transient === true
    );
  } catch {
    return false;
  }
};
