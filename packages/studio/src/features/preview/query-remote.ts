export const syncEditorQuery = async (
  queryUrl: string,
  serverToken: string,
  query: string,
  signal?: AbortSignal,
): Promise<void> => {
  const response = await fetch(queryUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Marimo-Server-Token": serverToken,
    },
    body: JSON.stringify({ query }),
    signal,
  });
  if (!response.ok) {
    throw new Error(`Query synchronization failed with ${response.status}`);
  }
};
