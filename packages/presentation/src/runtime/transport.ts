import type { MountConfig } from "@marimo-studio/protocol/runtime-config";

import {
  DOCUMENT_LIFECYCLE_QUERY_PARAM,
  DOCUMENT_REPLAY_QUERY_PARAM,
  publicNotebookQuery,
  SERVER_INSTANCE_QUERY_PARAM,
  STUDIO_CLIENT_QUERY_PARAM,
} from "@marimo-studio/protocol/query";
import { RUNTIME_QUERY_KEY } from "@marimo-studio/protocol/runtime-selection";

import { getMountConfig } from "../runtime-config/index.ts";

export const createServerTransportURL =
  (
    editMode: boolean,
    file: string | undefined,
    serverInstance: string,
    presentationSessionId: string,
    pageSearch = globalThis.location.search,
    identity: Pick<MountConfig, "clientId" | "lifecycleId" | "replay"> = getMountConfig(),
  ): ((url: URL) => URL) =>
  (url) => {
    url.search = publicNotebookQuery(pageSearch);
    if (file) {
      url.searchParams.set("file", file);
    }
    if (editMode) {
      url.searchParams.set("kiosk", "true");
    }
    url.searchParams.set("session_id", presentationSessionId);
    url.searchParams.set(SERVER_INSTANCE_QUERY_PARAM, serverInstance);
    if (editMode && identity.clientId && identity.lifecycleId) {
      url.searchParams.set(STUDIO_CLIENT_QUERY_PARAM, identity.clientId);
      url.searchParams.set(DOCUMENT_LIFECYCLE_QUERY_PARAM, String(identity.lifecycleId));
    }
    if (!editMode && identity.replay) {
      url.searchParams.set(DOCUMENT_REPLAY_QUERY_PARAM, "1");
    }
    url.searchParams.delete(RUNTIME_QUERY_KEY);
    return url;
  };
