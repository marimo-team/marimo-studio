import { parseRuntimeConfig } from "@marimo-studio/protocol/runtime-config";
import { appendUrlPath } from "@marimo-studio/protocol/url";
import { z } from "zod";

export type RuntimeControlRequestErrorCode =
  | "control-configuration-failed"
  | "presentation-revision-unavailable"
  | "runtime-sync-pending";

export class RuntimeControlRequestError extends Error {
  constructor(
    readonly code: RuntimeControlRequestErrorCode,
    readonly status: number,
    readonly transient: boolean,
    message: string,
  ) {
    super(message);
    this.name = "RuntimeControlRequestError";
  }
}

import type { RuntimeCellMap } from "./control-sync.ts";

export interface RuntimeControlSnapshot {
  schema: 1;
  revision: string;
  runtime: string;
  controls: RuntimeCellMap;
}

export type RuntimeControlResult =
  | { readonly kind: "changed"; readonly snapshot: RuntimeControlSnapshot; readonly etag: string }
  | { readonly kind: "unchanged"; readonly etag: string };

const runtimeControlSnapshotSchema = z.strictObject({
  schema: z.literal(1),
  revision: z.string().min(1),
  runtime: z.string().min(1),
  controlRevision: z.int().nonnegative(),
  controls: runtimeControlsSchema.optional(),
});
const runtimeControlRequestErrorCodeSchema = z.enum([
  "presentation-revision-unavailable",
  "runtime-sync-pending",
]);
const MAX_CONTROL_ERROR_BYTES = 16 * 1024;

const readControlError = async (response: Response): Promise<RuntimeControlRequestError> => {
  const fallback = `Control configuration failed with ${response.status}`;
  const length = response.headers.get("Content-Length");
  if (length !== null && /^\d+$/u.test(length) && Number(length) > MAX_CONTROL_ERROR_BYTES) {
    await response.body?.cancel();
    return new RuntimeControlRequestError(
      "control-configuration-failed",
      response.status,
      false,
      fallback,
    );
  }
  const reader = response.body?.getReader();
  if (reader === undefined) {
    return new RuntimeControlRequestError(
      "control-configuration-failed",
      response.status,
      false,
      fallback,
    );
  }
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) {
        break;
      }
      size += chunk.value.byteLength;
      if (size > MAX_CONTROL_ERROR_BYTES) {
        await reader.cancel();
        return new RuntimeControlRequestError(
          "control-configuration-failed",
          response.status,
          false,
          fallback,
        );
      }
      chunks.push(chunk.value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try {
    const detail = parseErrorResponse(
      parsePortableJson(new TextDecoder("utf-8", { fatal: true }).decode(bytes)),
    );
    const code = runtimeControlRequestErrorCodeSchema.safeParse(detail.error);
    return new RuntimeControlRequestError(
      code.success ? code.data : "control-configuration-failed",
      response.status,
      detail.transient === true,
      detail.message ?? fallback,
    );
  } catch {
    return new RuntimeControlRequestError(
      "control-configuration-failed",
      response.status,
      false,
      fallback,
    );
  }
};

export const fetchRuntimeControls = async (
  supportUrl: string,
  runtime: string,
  sessionId: string,
  revision: string,
  clientId: string,
  etag?: string,
  signal?: AbortSignal,
): Promise<RuntimeControlResult> => {
  const url = new URL(appendUrlPath(supportUrl, "controls", globalThis.location.href));
  url.searchParams.set("runtime", runtime);
  url.searchParams.set("revision", revision);
  url.searchParams.set("marimo_studio_client", clientId);
  const headers = new Headers({ "Marimo-Session-Id": sessionId });
  if (etag !== undefined) {
    headers.set("If-None-Match", etag);
  }
  const response = await fetch(url, {
    cache: "no-store",
    headers,
    signal,
  });
  if (response.status !== 304 && !response.ok) {
    throw await readControlError(response);
  }
  const responseEtag = response.headers.get("ETag");
  if (!responseEtag) {
    throw new Error("Control configuration did not include an ETag");
  }
  if (response.status === 304) {
    return { kind: "unchanged", etag: responseEtag };
  }
  const snapshot = runtimeControlSnapshotSchema.parse(await response.json());
  if (snapshot.runtime !== runtime) {
    throw new Error(
      `Control configuration selected ${JSON.stringify(snapshot.runtime)} instead of ${JSON.stringify(runtime)}.`,
    );
  }
  return {
    revision: config.revision,
    runtime: config.runtime.id,
    controls: { cells: config.runtimeBindings.cellRefs },
  };
};
