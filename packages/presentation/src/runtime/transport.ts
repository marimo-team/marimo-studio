import { RUNTIME_QUERY_KEY } from "@marimo-studio/protocol/runtime-selection";

export const createServerTransportURL =
  (editMode: boolean, file?: string): ((url: URL) => URL) =>
  (url) => {
    url.searchParams.delete(RUNTIME_QUERY_KEY);
    url.searchParams.delete("file");
    if (file) {
      url.searchParams.set("file", file);
    }
    if (editMode) {
      url.searchParams.set("kiosk", "true");
    }
    return url;
  };
