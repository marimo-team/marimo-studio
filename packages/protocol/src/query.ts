export const QUERY_OPERATION_QUERY_PARAM = "marimo_studio_query_operation";

const PRIVATE_QUERY_KEYS = [
  "access_token",
  "file",
  "kiosk",
  "marimo_studio_client",
  QUERY_OPERATION_QUERY_PARAM,
  "marimo_studio_resume",
  "marimo_studio_view",
  "refresh_token",
  "session_id",
  "runtime",
] as const;

export const publicNotebookQuery = (search: string): string => {
  const parameters = new URLSearchParams(search);
  for (const key of PRIVATE_QUERY_KEYS) {
    parameters.delete(key);
  }
  const query = parameters.toString();
  return query ? `?${query}` : "";
};

export const notebookRouteQuery = (search: string): string => {
  const input = new URLSearchParams(search);
  const output = new URLSearchParams();
  const file = input.get("file");
  if (file !== null) {
    output.set("file", file);
  }
  const query = output.toString();
  return query ? `?${query}` : "";
};

export const notebookQueryValues = (search: string): Record<string, string | string[]> => {
  const parameters = new URLSearchParams(publicNotebookQuery(search));
  return Object.fromEntries(
    Array.from(new Set(parameters.keys()), (key) => {
      const values = parameters.getAll(key);
      return [key, values.length === 1 ? values[0] : values];
    }),
  );
};
