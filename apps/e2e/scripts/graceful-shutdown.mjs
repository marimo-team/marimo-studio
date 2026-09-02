import { z } from "zod";

const POLL_INTERVAL = 50;
const sessionInventorySchema = z.object({
  files: z.array(z.object({ sessionId: z.string() })),
});

const requestWithin = async (url, deadline, options = {}) => {
  const remaining = deadline - Date.now();
  if (remaining <= 0) throw new Error("Notebook session shutdown timed out");
  return fetch(url, {
    ...options,
    signal: AbortSignal.timeout(remaining),
  });
};

const readSessionInventory = async (apiRoot, headers, deadline) => {
  const response = await requestWithin(`${apiRoot}/running_notebooks`, deadline, {
    headers,
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`Marimo session inventory returned ${response.status}`);
  }
  return sessionInventorySchema.parse(await response.json()).files;
};

const shutdownSession = async (apiRoot, headers, sessionId, deadline) => {
  const response = await requestWithin(`${apiRoot}/shutdown_session`, deadline, {
    body: JSON.stringify({ sessionId }),
    headers: { ...headers, "Content-Type": "application/json" },
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`Marimo session shutdown returned ${response.status}`);
  }
};

const drainSessions = async (apiRoot, headers, deadline) => {
  while (true) {
    const sessions = await readSessionInventory(apiRoot, headers, deadline);
    if (sessions.length === 0) return;
    for (const { sessionId } of sessions) {
      await shutdownSession(apiRoot, headers, sessionId, deadline);
    }
    const remaining = deadline - Date.now();
    if (remaining <= 0) throw new Error("Notebook session shutdown timed out");
    await new Promise((resolveWait) => setTimeout(resolveWait, Math.min(POLL_INTERVAL, remaining)));
  }
};

const accessHeaders = (authToken) => (authToken ? { Authorization: `Bearer ${authToken}` } : {});

export const requestStudioShutdown = async (serverUrl, authToken, timeout = 5_000) => {
  const authorization = accessHeaders(authToken);
  const deadline = Date.now() + timeout;
  const documentResponse = await requestWithin(`${serverUrl}/?file=notebook.py`, deadline, {
    headers: authorization,
  });
  if (!documentResponse.ok) {
    throw new Error(`Marimo bootstrap returned ${documentResponse.status}`);
  }
  const document = await documentResponse.text();
  const token = document.match(/"serverToken":"([^"]+)"/)?.[1];
  if (!token) {
    throw new Error("Studio bootstrap did not contain a server token");
  }
  const headers = { ...authorization, "Marimo-Server-Token": token };
  await drainSessions(`${serverUrl}/api/home`, headers, deadline);
  const response = await requestWithin(`${serverUrl}/api/kernel/shutdown`, deadline, {
    headers,
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`Marimo shutdown returned ${response.status}`);
  }
};
