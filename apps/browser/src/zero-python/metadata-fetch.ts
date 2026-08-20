import { parsePortableJson } from "@marimo-team/portable-json";

import type { StudioPreparedManifest } from "./metadata-records.ts";

import { ZeroPythonRuntimeError } from "./errors.ts";
import { parseStudioPreparedManifest } from "./metadata-records.ts";

const MANIFEST_MAX_BYTES = 256 * 1024;

export const fetchStudioPreparedManifest = async (
  url: URL,
  fetcher: typeof globalThis.fetch,
  signal: AbortSignal | undefined,
): Promise<StudioPreparedManifest> => {
  signal?.throwIfAborted();
  let response: Response;
  try {
    const request: RequestInit = {
      cache: "no-store",
      headers: { Accept: "application/json" },
    };
    if (signal !== undefined) request.signal = signal;
    response = await fetcher(url, request);
  } catch (error) {
    if (signal?.aborted) {
      throw signal.reason ?? error;
    }
    throw new ZeroPythonRuntimeError(
      "manifest_read_failed",
      "The Studio prepared manifest could not be read.",
      { cause: error },
    );
  }
  if (!response.ok) {
    await response.body?.cancel().catch(() => {});
    throw new ZeroPythonRuntimeError(
      "manifest_read_failed",
      `The Studio prepared manifest request failed with ${response.status}.`,
    );
  }
  const bytes = await readManifestBytes(response, signal);
  try {
    const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    return parseStudioPreparedManifest(parsePortableJson(text));
  } catch (error) {
    if (error instanceof ZeroPythonRuntimeError) {
      throw error;
    }
    throw new ZeroPythonRuntimeError(
      "manifest_invalid",
      "The Studio prepared manifest is invalid.",
      {
        cause: error,
      },
    );
  }
};

const manifestTooLarge = (): ZeroPythonRuntimeError =>
  new ZeroPythonRuntimeError(
    "manifest_read_failed",
    `The Studio prepared manifest exceeds ${MANIFEST_MAX_BYTES} bytes.`,
  );

const readManifestBytes = async (
  response: Response,
  signal: AbortSignal | undefined,
): Promise<Uint8Array> => {
  if (signal?.aborted) {
    await response.body?.cancel().catch(() => {});
    signal.throwIfAborted();
  }
  const length = response.headers.get("Content-Length");
  if (length !== null && /^\d+$/u.test(length) && Number(length) > MANIFEST_MAX_BYTES) {
    await response.body?.cancel().catch(() => {});
    throw manifestTooLarge();
  }
  const reader = response.body?.getReader();
  if (reader === undefined) {
    return new Uint8Array();
  }
  const chunks: Uint8Array[] = [];
  let size = 0;
  const abort = () => {
    void reader.cancel(signal?.reason).catch(() => {});
  };
  signal?.addEventListener("abort", abort, { once: true });
  try {
    signal?.throwIfAborted();
    while (true) {
      signal?.throwIfAborted();
      const chunk = await reader.read();
      signal?.throwIfAborted();
      if (chunk.done) {
        break;
      }
      size += chunk.value.byteLength;
      if (size > MANIFEST_MAX_BYTES) {
        await reader.cancel();
        throw manifestTooLarge();
      }
      chunks.push(chunk.value);
    }
  } catch (error) {
    if (signal?.aborted) {
      throw signal.reason ?? error;
    }
    if (error instanceof ZeroPythonRuntimeError) {
      throw error;
    }
    throw new ZeroPythonRuntimeError(
      "manifest_read_failed",
      "The Studio prepared manifest body could not be read.",
      { cause: error },
    );
  } finally {
    signal?.removeEventListener("abort", abort);
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes;
};
