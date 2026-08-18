import { SERVER_INSTANCE_QUERY_PARAM } from "@marimo-studio/protocol/query";
import { RUNTIME_QUERY_KEY } from "@marimo-studio/protocol/runtime-selection";

export const createServerTransportURL =
  (editMode: boolean, file: string | undefined, serverInstance: string): ((url: URL) => URL) =>
  (url) => {
    url.searchParams.delete(RUNTIME_QUERY_KEY);
    url.searchParams.delete("file");
    if (file) {
      url.searchParams.set("file", file);
    }
    if (editMode) {
      url.searchParams.set("kiosk", "true");
    }
    url.searchParams.set(SERVER_INSTANCE_QUERY_PARAM, serverInstance);
    return url;
  };
