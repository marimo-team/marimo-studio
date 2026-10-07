import { parseErrorResponse } from "@marimo-studio/protocol/errors";
import { editorControlsSchema } from "@marimo-studio/protocol/frame-bridge";
import { STUDIO_CLIENT_QUERY_PARAM } from "@marimo-studio/protocol/query";
import { jsonValueSchema } from "@marimo-studio/protocol/runtime-config";
import { appendUrlPath } from "@marimo-studio/protocol/url";

import type { RuntimeCellMap } from "./control-sync.ts";

export interface RuntimeControlSnapshot {
  revision: string;
  controls: RuntimeCellMap;
}

export class ControlRequestError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly transient: boolean,
    readonly hint?: string,
  ) {
    super(message);
    this.name = "ControlRequestError";
  }
}

export const fetchRuntimeControls = async (
  supportUrl: string,
  clientId: string,
  sessionId: string,
  revision: string,
  signal?: AbortSignal,
): Promise<RuntimeControlSnapshot> => {
  const url = new URL(appendUrlPath(supportUrl, "controls"));
  url.searchParams.set(STUDIO_CLIENT_QUERY_PARAM, clientId);
  url.searchParams.set("revision", revision);
  const response = await fetch(url, {
    cache: "no-store",
    headers: { "Marimo-Session-Id": sessionId },
    signal,
  });
  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch (error) {
      if (signal?.aborted) {
        throw error;
      }
    }
    const parsed = jsonValueSchema.safeParse(body);
    const detail = parseErrorResponse(parsed.success ? parsed.data : null);
    throw new ControlRequestError(
      detail.message ?? `Control configuration failed with ${response.status}`,
      detail.error ?? "control-request-failed",
      detail.transient ?? true,
      detail.hint,
    );
  }
  return editorControlsSchema.parse(await response.json());
};
