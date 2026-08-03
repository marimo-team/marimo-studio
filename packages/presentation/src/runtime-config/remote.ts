import { parseErrorResponse } from "@marimo-studio/protocol/errors";
import { parseRuntimeConfig, type RuntimeConfig } from "@marimo-studio/protocol/runtime-config";

import { retry } from "../retry.ts";

const responseText = async (response: Response, fallback: string) => {
  if (response.headers.get("content-type")?.includes("text/html")) {
    return fallback;
  }
  return (await response.text()).trim() || fallback;
};

export const readResponseError = async (
  response: Response,
  fallback: string,
): Promise<{
  code: string;
  message: string;
  hint: string;
  transient: boolean;
}> => {
  const payload: unknown = await response
    .clone()
    .json()
    .catch(() => undefined);
  const detail = parseErrorResponse(payload);
  return {
    code: detail.error ?? "runtime-config-failed",
    message: detail.message ?? (await responseText(response, fallback)),
    hint: detail.hint ?? "",
    transient: detail.transient ?? false,
  };
};

export class RuntimeConfigRequestError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly transient: boolean,
    readonly hint = "",
  ) {
    super(message);
    this.name = "RuntimeConfigRequestError";
  }
}

export const runtimeConfigSessionId = ({
  connected,
  href,
}: {
  connected?: string;
  href?: string;
}): string | undefined => {
  if (connected) {
    return connected;
  }
  try {
    const url = new URL(href ?? "");
    if (url.searchParams.get("marimo_studio_resume") === "1") {
      return url.searchParams.get("session_id") ?? undefined;
    }
  } catch {
    return undefined;
  }
  return undefined;
};

export const fetchRuntimeConfig = async (
  supportUrl: string,
  signal?: AbortSignal,
): Promise<RuntimeConfig> => {
  const browser = globalThis as typeof globalThis & Window;
  const sessionId = runtimeConfigSessionId({
    connected: browser.__MARIMO_STUDIO_SESSION_ID__,
    href: browser.location?.href,
  });
  const response = await fetch(`${supportUrl}/config`, {
    cache: "no-store",
    headers: sessionId ? { "Marimo-Session-Id": sessionId } : undefined,
    signal,
  });
  if (!response.ok) {
    const detail = await readResponseError(
      response,
      `Runtime config failed with ${response.status}`,
    );
    throw new RuntimeConfigRequestError(detail.message, detail.code, detail.transient, detail.hint);
  }
  return parseRuntimeConfig(await response.json());
};

const RETRY_DELAYS = [100, 250, 500, 1_000] as const;

export const fetchRuntimeConfigWithRetry = async (
  supportUrl: string,
  signal?: AbortSignal,
): Promise<RuntimeConfig> =>
  retry({
    operation: () => fetchRuntimeConfig(supportUrl, signal),
    delays: RETRY_DELAYS,
    retryWhen: (error) => error instanceof RuntimeConfigRequestError && error.transient,
    signal,
  });

export const requireMatchingPresentationRevision = (
  documentRevision: string | null,
  config: RuntimeConfig,
): void => {
  if (documentRevision === config.revision) {
    return;
  }
  throw new RuntimeConfigRequestError(
    "The view document and notebook bindings changed at the same time. " +
      "Studio will retry with one source revision.",
    "presentation-revision-mismatch",
    true,
    "Wait for the current view sources to settle.",
  );
};

export const fetchRuntimeConfigForRevision = async (
  supportUrl: string,
  documentRevision: string,
  signal?: AbortSignal,
): Promise<RuntimeConfig> => {
  const config = await fetchRuntimeConfigWithRetry(supportUrl, signal);
  requireMatchingPresentationRevision(documentRevision, config);
  return config;
};
