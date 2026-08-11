import { parseRuntimeConfig, type RuntimeControls } from "@marimo-studio/protocol/runtime-config";
import { appendUrlPath } from "@marimo-studio/protocol/url";

export interface RuntimeControlSnapshot {
  revision: string;
  runtime: string;
  controls?: RuntimeControls;
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
    controls: config.runtime.controls,
  };
};
