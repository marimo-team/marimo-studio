import { parseRuntimeConfig } from "@marimo-studio/protocol/runtime-config";
import { appendUrlPath } from "@marimo-studio/protocol/url";

import type { RuntimeCellMap } from "./control-sync.ts";

export interface RuntimeControlSnapshot {
  revision: string;
  runtime: string;
  controls: RuntimeCellMap;
}

export const fetchRuntimeControls = async (
  supportUrl: string,
  runtime: string,
  sessionId: string,
  signal?: AbortSignal,
): Promise<RuntimeControlSnapshot> => {
  const url = new URL(appendUrlPath(supportUrl, "config", globalThis.location.href));
  url.searchParams.set("runtime", runtime);
  const response = await fetch(url, {
    cache: "no-store",
    headers: { "Marimo-Session-Id": sessionId },
    signal,
  });
  if (!response.ok) {
    throw new Error(`Control configuration failed with ${response.status}`);
  }
  const config = parseRuntimeConfig(await response.json());
  if (config.runtime.id !== runtime) {
    throw new Error(
      `Control configuration selected ${JSON.stringify(config.runtime.id)} instead of ${JSON.stringify(runtime)}.`,
    );
  }
  return {
    revision: config.revision,
    runtime: config.runtime.id,
    controls: { cells: config.runtimeBindings.cellRefs },
  };
};
