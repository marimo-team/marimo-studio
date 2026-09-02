import {
  DOCUMENT_LIFECYCLE_QUERY_PARAM,
  SERVER_INSTANCE_QUERY_PARAM,
} from "@marimo-studio/protocol/query";

export const standaloneViewUrl = (source: string): string => {
  const url = new URL(source, globalThis.location.href);
  for (const key of [
    DOCUMENT_LIFECYCLE_QUERY_PARAM,
    SERVER_INSTANCE_QUERY_PARAM,
    "marimo_studio_resume",
    "session_id",
  ]) {
    url.searchParams.delete(key);
  }
  return url.toString();
};
