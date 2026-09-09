import type { RuntimeConfig } from "@marimo-studio/protocol/runtime-config";
import type { RuntimeProgress } from "@marimo-studio/protocol/runtime-progress";

import { parseErrorResponse } from "@marimo-studio/protocol/errors";
import {
  RUNTIME_CONFIG_STREAM_MAX_LINE_BYTES,
  runtimeConfigPacketSchema,
} from "@marimo-studio/protocol/runtime-config-stream";

import { parseJson } from "../json.ts";
import { RuntimeConfigRequestError } from "./error.ts";

const streamError = (message: string) =>
  new RuntimeConfigRequestError(message, "runtime-config-stream-invalid", false);

const readPacket = (line: string) => {
  try {
    return runtimeConfigPacketSchema.parse(parseJson(line));
  } catch {
    throw streamError("Runtime configuration stream contained an invalid record.");
  }
};

export const readRuntimeConfigStream = async (
  response: Response,
  report: (progress: RuntimeProgress) => void,
  signal?: AbortSignal,
): Promise<RuntimeConfig> => {
  if (!response.body) throw streamError("Runtime configuration stream has no body.");
  // Chromium can report direct reads of no-store streams as aborted at EOF.
  // A native Response clone preserves completion. Close its unused branch immediately.
  const unusedClosed = response
    .clone()
    .body?.cancel()
    .catch(() => {});
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let pending = "";
  let lineBytes = 0;
  let ended = false;
  let terminal: Exclude<ReturnType<typeof readPacket>, { type: "progress" }> | undefined;
  const abort = () => {
    void reader.cancel(signal?.reason).catch(() => {});
  };
  signal?.addEventListener("abort", abort, { once: true });
  try {
    while (true) {
      signal?.throwIfAborted();
      const { done, value } = await reader.read().catch((cause: unknown) => {
        signal?.throwIfAborted();
        throw new RuntimeConfigRequestError(
          cause instanceof Error ? cause.message : "Runtime configuration stream disconnected.",
          "runtime-config-unavailable",
          true,
          "Wait for the Studio server to become available.",
        );
      });
      signal?.throwIfAborted();
      if (done) {
        ended = true;
        if (lineBytes > 0 || pending.length > 0 || terminal === undefined) {
          throw streamError("Runtime configuration stream ended before completion.");
        }
        if (terminal.type === "config") return terminal.config;
        const { type: _type, error, message, transient, hint, ...details } = terminal;
        throw new RuntimeConfigRequestError(
          message,
          error,
          transient ?? false,
          hint ?? "",
          parseErrorResponse(details),
        );
      }
      for (const byte of value) {
        lineBytes = byte === 10 ? 0 : lineBytes + 1;
        if (lineBytes > RUNTIME_CONFIG_STREAM_MAX_LINE_BYTES)
          throw streamError("Runtime configuration record is too large.");
      }
      const previousLength = pending.length;
      try {
        pending += decoder.decode(value, { stream: true });
      } catch {
        throw streamError("Runtime configuration stream contained invalid UTF-8.");
      }
      let newline = pending.indexOf("\n", previousLength);
      while (newline !== -1) {
        const line = pending.slice(0, newline);
        pending = pending.slice(newline + 1);
        if (terminal !== undefined) {
          throw streamError("Runtime configuration stream continued after completion.");
        }
        const packet = readPacket(line);
        if (packet.type === "progress") {
          report(packet.progress);
        } else {
          terminal = packet;
        }
        newline = pending.indexOf("\n");
      }
    }
  } finally {
    signal?.removeEventListener("abort", abort);
    if (!ended) await reader.cancel().catch(() => {});
    reader.releaseLock();
    await unusedClosed;
  }
};
