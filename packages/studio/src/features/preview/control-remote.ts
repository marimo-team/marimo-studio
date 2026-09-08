import { editorControlsSchema } from "@marimo-studio/protocol/frame-bridge";
import { STUDIO_CLIENT_QUERY_PARAM } from "@marimo-studio/protocol/query";
import { appendUrlPath } from "@marimo-studio/protocol/url";

import type { RuntimeCellMap } from "./control-sync.ts";

export interface RuntimeControlSnapshot {
  revision: string;
  controls: RuntimeCellMap;
}

export const fetchRuntimeControls = async (
  supportUrl: string,
  clientId: string,
  sessionId: string,
  revision: string,
  signal?: AbortSignal,
): Promise<RuntimeControlSnapshot> => {
  const url = new URL(appendUrlPath(supportUrl, "controls", globalThis.location.href));
  url.searchParams.set(STUDIO_CLIENT_QUERY_PARAM, clientId);
  url.searchParams.set("revision", revision);
  const response = await fetch(url, {
    cache: "no-store",
    headers: { "Marimo-Session-Id": sessionId },
    signal,
  });
  if (!response.ok) {
    throw new Error(`Control configuration failed with ${response.status}`);
  }
  return editorControlsSchema.parse(await response.json());
};
