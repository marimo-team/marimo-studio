import { z } from "zod";

const POLL_INTERVAL = 50;
const sessionInventorySchema = z.object({
  files: z.array(z.object({ sessionId: z.string() })),
});

const requestWithin = async (url: string, deadline: number, options: RequestInit = {}) => {
  const remaining = deadline - Date.now();
  if (remaining <= 0) throw new Error("Notebook session shutdown timed out");
  return fetch(url, {
    ...options,
    signal: AbortSignal.timeout(remaining),
  });
};

const readSessionInventory = async (apiRoot: string, headers: Headers, deadline: number) => {
  const response = await requestWithin(`${apiRoot}/running_notebooks`, deadline, {
    headers,
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`Marimo session inventory returned ${response.status}`);
  }
  return sessionInventorySchema.parse(await response.json()).files;
};

const shutdownSession = async (
  apiRoot: string,
  headers: Headers,
  sessionId: string,
  deadline: number,
) => {
  const contentHeaders = new Headers(headers);
  contentHeaders.set("Content-Type", "application/json");
  const response = await requestWithin(`${apiRoot}/shutdown_session`, deadline, {
    body: JSON.stringify({ sessionId }),
    headers: contentHeaders,
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`Marimo session shutdown returned ${response.status}`);
  }
};

const drainSessions = async (apiRoot: string, headers: Headers, deadline: number) => {
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

export const requestStudioShutdown = async (
  serverUrl: string,
  authToken = "",
  timeout = 5_000,
  studioEntry = "",
) => {
  const headers = new Headers(authToken ? { Authorization: `Bearer ${authToken}` } : {});
  const deadline = Date.now() + timeout;
  const entrySession = studioEntry ? "&session_id=s_shutdn" : "";
  const documentResponse = await requestWithin(
    `${serverUrl}${studioEntry}/?file=notebook.py${entrySession}`,
    deadline,
    {
      headers,
    },
  );
  if (!documentResponse.ok) {
    throw new Error(`Marimo bootstrap returned ${documentResponse.status}`);
  }
  const document = await documentResponse.text();
  const token = document.match(/"serverToken":"([^"]+)"/)?.[1];
  if (!token) {
    throw new Error("Studio bootstrap did not contain a server token");
  }
  headers.set("Marimo-Server-Token", token);
  await drainSessions(`${serverUrl}/api/home`, headers, deadline);
  const response = await requestWithin(`${serverUrl}/api/kernel/shutdown`, deadline, {
    headers,
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`Marimo shutdown returned ${response.status}`);
  }
};
