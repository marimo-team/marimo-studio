const PRIVATE_QUERY_KEYS = [
  "access_token",
  "file",
  "kiosk",
  "marimo_studio_resume",
  "refresh_token",
  "session_id",
] as const;

export const publicNotebookQuery = (search: string): string => {
  const parameters = new URLSearchParams(search);
  for (const key of PRIVATE_QUERY_KEYS) {
    parameters.delete(key);
  }
  const query = parameters.toString();
  return query ? `?${query}` : "";
};
