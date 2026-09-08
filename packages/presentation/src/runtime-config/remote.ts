import {
  type MountConfig,
  parseRuntimeConfig,
  type RuntimeConfig,
} from "@marimo-studio/protocol/runtime-config";
import { RUNTIME_CONFIG_STREAM_TYPE } from "@marimo-studio/protocol/runtime-config-stream";
import { DEFAULT_RUNTIME_ID } from "@marimo-studio/protocol/runtime-selection";
import { appendUrlPath } from "@marimo-studio/protocol/url";

import { responseJson } from "../json.ts";
import { retry } from "../retry.ts";
import { readResponseError, RuntimeConfigRequestError } from "./error.ts";
import { runtimeProgress } from "./progress.ts";
import { getMountConfig } from "./store.ts";
import { readRuntimeConfigStream } from "./stream.ts";

const PREVIEW_SESSION_HEADER = "Marimo-Studio-Preview-Session-Id";

export const runtimeConfigSessionId = ({
  connected,
  mounted = getMountConfig().runtime === "server" ? getMountConfig().runtimeSessionId : undefined,
  server = getMountConfig().runtime === "server",
}: {
  connected?: string;
  mounted?: string;
  server?: boolean;
}): string | undefined => (server ? (mounted ?? connected) : undefined);

export const fetchRuntimeConfig = async (
  supportUrl: string,
  signal?: AbortSignal,
  runtime = DEFAULT_RUNTIME_ID,
  previewSessionId?: string,
  revision?: string,
  runtimeSessionId?: string,
  mount: Pick<MountConfig, "clientId" | "runtime" | "runtimeSessionId"> = getMountConfig(),
): Promise<RuntimeConfig> => {
  const sessionId = runtimeConfigSessionId({
    connected: runtimeSessionId ?? globalThis.__MARIMO_STUDIO_SESSION_ID__,
    mounted: mount.runtime === "server" ? mount.runtimeSessionId : undefined,
    server: mount.runtime === "server",
  });
  const url = new URL(appendUrlPath(supportUrl, "config", globalThis.location.href));
  url.searchParams.set("runtime", runtime);
  if (revision) {
    url.searchParams.set("revision", revision);
  }
  const clientId = mount.clientId;
  if (clientId) {
    url.searchParams.set("marimo_studio_client", clientId);
    if (!previewSessionId) {
      throw new RuntimeConfigRequestError(
        "The Studio preview session is not initialized.",
        "preview-session-unavailable",
        false,
      );
    }
  }
  const headers = new Headers();
  if (previewSessionId) {
    headers.set(PREVIEW_SESSION_HEADER, previewSessionId);
  }
  if (sessionId) {
    headers.set("Marimo-Session-Id", sessionId);
  }
  const operation = runtimeProgress.begin(
    runtime,
    supportUrl,
    revision ?? getMountConfig().revision,
  );
  let configured = false;
  try {
    headers.set("Accept", RUNTIME_CONFIG_STREAM_TYPE);
    let response: Response;
    try {
      response = await fetch(url, {
        cache: "no-store",
        headers,
        signal,
      });
    } catch (error) {
      if (signal?.aborted) {
        throw error;
      }
      throw new RuntimeConfigRequestError(
        error instanceof Error ? error.message : "Runtime config request failed.",
        "runtime-config-unavailable",
        true,
        "Wait for the Studio server to become available.",
      );
    }
    if (!response.ok) {
      const detail = await readResponseError(
        response,
        `Runtime config failed with ${response.status}`,
      );
      throw new RuntimeConfigRequestError(
        detail.message,
        detail.code,
        detail.transient,
        detail.hint,
      );
    }
    const config =
      response.headers.get("content-type")?.split(";", 1)[0]?.trim() === RUNTIME_CONFIG_STREAM_TYPE
        ? await readRuntimeConfigStream(response, operation.report, signal)
        : parseRuntimeConfig(await responseJson(response));
    if (config.runtime.id !== runtime) {
      throw new RuntimeConfigRequestError(
        `The server selected ${JSON.stringify(config.runtime.id)} instead of ${JSON.stringify(runtime)}.`,
        "runtime-selection-mismatch",
        false,
      );
    }
    configured = true;
    return config;
  } finally {
    operation.close(configured);
  }
};

const RETRY_DELAYS = [100, 250, 500, 1_000] as const;

export const fetchRuntimeConfigWithRetry = async (
  supportUrl: string,
  signal?: AbortSignal,
  runtime = DEFAULT_RUNTIME_ID,
  previewSessionId?: string,
  revision?: string,
  runtimeSessionId?: string,
): Promise<RuntimeConfig> =>
  retry({
    operation: () =>
      fetchRuntimeConfig(supportUrl, signal, runtime, previewSessionId, revision, runtimeSessionId),
    delays: RETRY_DELAYS,
    retryWhen: (error) =>
      error instanceof RuntimeConfigRequestError &&
      error.transient &&
      error.code !== "presentation-revision-unavailable",
    retryAfterExhaustion: (error) =>
      error instanceof RuntimeConfigRequestError && error.code === "runtime-startup-pending"
        ? 5_000
        : undefined,
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
    "The view document and notebook symbol graph changed at the same time. " +
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
  runtime = DEFAULT_RUNTIME_ID,
  previewSessionId?: string,
  runtimeSessionId?: string,
): Promise<RuntimeConfig> => {
  const config = await fetchRuntimeConfigWithRetry(
    supportUrl,
    signal,
    runtime,
    previewSessionId,
    documentRevision,
    runtimeSessionId,
  );
  requireMatchingPresentationRevision(documentRevision, config);
  return config;
};

export const fetchCurrentRuntimeConfig = async (
  documentUrl: string,
  supportUrl: string,
  runtime = DEFAULT_RUNTIME_ID,
  previewSessionId?: string,
  runtimeSessionId?: string,
  signal?: AbortSignal,
): Promise<RuntimeConfig> =>
  retry({
    operation: async () => {
      const headers = new Headers();
      if (previewSessionId) {
        headers.set(PREVIEW_SESSION_HEADER, previewSessionId);
      }
      const document = await fetch(documentUrl, {
        cache: "no-store",
        headers,
        method: "HEAD",
        signal,
      });
      if (!document.ok) {
        const detail = await readResponseError(
          document,
          `Presentation revision check failed with ${document.status}`,
        );
        throw new RuntimeConfigRequestError(
          detail.message,
          detail.code,
          detail.transient,
          detail.hint,
        );
      }
      const revision = document.headers.get("Marimo-Studio-Revision");
      if (!revision) {
        throw new RuntimeConfigRequestError(
          "The view document did not identify its presentation revision.",
          "presentation-revision-missing",
          true,
          "Wait for the current view sources to settle.",
        );
      }
      const config = await fetchRuntimeConfig(
        supportUrl,
        signal,
        runtime,
        previewSessionId,
        revision,
        runtimeSessionId,
      );
      requireMatchingPresentationRevision(revision, config);
      return config;
    },
    delays: RETRY_DELAYS,
    retryWhen: (error) => error instanceof RuntimeConfigRequestError && error.transient,
    retryAfterExhaustion: (error) =>
      error instanceof RuntimeConfigRequestError && error.code === "runtime-startup-pending"
        ? 5_000
        : undefined,
    signal,
  });
