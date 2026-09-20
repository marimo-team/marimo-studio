export const QUERY_OPERATION_QUERY_PARAM = "marimo_studio_query_operation";
export const SERVER_INSTANCE_QUERY_PARAM = "marimo_studio_server";
export const DOCUMENT_LIFECYCLE_QUERY_PARAM = "marimo_studio_lifecycle";
export const STUDIO_CLIENT_QUERY_PARAM = "marimo_studio_client";
export const WORKSPACE_STREAM_QUERY_PARAM = "marimo_studio_connection";
export const WORKSPACE_EVENTS_CAPABILITY_QUERY_PARAM = "marimo_studio_events";
export const EDITOR_BINDING_CAPABILITY_QUERY_PARAM = "marimo_studio_editor";
export const PRESENTATION_RENEWAL_QUERY_PARAM = "marimo_studio_renewal";
export const UNFRAMED_QUERY_PARAM = "marimo_studio_unframed";
export const DOCUMENT_REPLAY_QUERY_PARAM = "marimo_studio_resume";

const PRIVATE_QUERY_KEYS = [
  "access_token",
  "file",
  "kiosk",
  STUDIO_CLIENT_QUERY_PARAM,
  QUERY_OPERATION_QUERY_PARAM,
  PRESENTATION_RENEWAL_QUERY_PARAM,
  SERVER_INSTANCE_QUERY_PARAM,
  DOCUMENT_LIFECYCLE_QUERY_PARAM,
  EDITOR_BINDING_CAPABILITY_QUERY_PARAM,
  WORKSPACE_EVENTS_CAPABILITY_QUERY_PARAM,
  WORKSPACE_STREAM_QUERY_PARAM,
  DOCUMENT_REPLAY_QUERY_PARAM,
  "marimo_studio_view",
  UNFRAMED_QUERY_PARAM,
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
