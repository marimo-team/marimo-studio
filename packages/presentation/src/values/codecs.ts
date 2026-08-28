import type * as ArrowModule from "@marimo-studio/marimo-frontend/arrow-table";
import type { JsonValue } from "@marimo-studio/protocol/runtime-config";
import type {
  ArrowValueDescriptor,
  ValueDescriptor,
  ValueReadError,
  ValueReadResponse,
} from "@marimo-studio/protocol/value-read";

import { errorMessage } from "../errors.ts";

const MAX_VALUE_BYTES = 1_000_000;
const retryableResourceStatus = (status: number): boolean =>
  status === 404 ||
  status === 408 ||
  status === 409 ||
  status === 425 ||
  status === 429 ||
  status >= 500;

export type MarimoValue = JsonValue | ArrowModule.MarimoArrowTable;

export type DecodedValue =
  | {
      readonly codec: "json-v1";
      readonly fingerprint: string;
      readonly value: JsonValue;
    }
  | {
      readonly codec: "arrow-ipc-v1";
      readonly fingerprint: string;
      readonly value: ArrowModule.MarimoArrowTable;
    };

type DecodedArrowValue = Extract<DecodedValue, { readonly codec: "arrow-ipc-v1" }>;

export interface DecodedValueReadResponse {
  readonly values: Record<string, DecodedValue>;
  readonly errors: Record<string, ValueReadError>;
}

export class ValueDecodeError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly transient = false,
  ) {
    super(message);
    this.name = "ValueDecodeError";
  }
}

let arrowModule: Promise<typeof ArrowModule> | undefined;

const loadArrowModule = (): Promise<typeof ArrowModule> => {
  arrowModule ??= import("@marimo-studio/marimo-frontend/arrow-table");
  return arrowModule;
};

const sha256Fingerprint = async (bytes: Uint8Array<ArrayBuffer>): Promise<string | undefined> => {
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) {
    return undefined;
  }
  const digest = new Uint8Array(await subtle.digest("SHA-256", bytes));
  const hex = Array.from(digest, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `sha256:${hex}`;
};

const readArrowBytes = async (
  descriptor: ArrowValueDescriptor,
  signal?: AbortSignal,
  baseUrl: string | URL = globalThis.location.href,
): Promise<Uint8Array<ArrayBuffer>> => {
  if (descriptor.byteLength > MAX_VALUE_BYTES) {
    throw new ValueDecodeError(
      "value-too-large",
      `The Arrow IPC value exceeds the ${MAX_VALUE_BYTES}-byte limit.`,
    );
  }
  let buffer: ArrayBuffer;
  try {
    const dataUrl = descriptor.dataUrl.startsWith("data:")
      ? descriptor.dataUrl
      : new URL(descriptor.dataUrl, baseUrl).toString();
    const response = await fetch(dataUrl, { signal });
    if (!response.ok) {
      throw new ValueDecodeError(
        "value-resource-unavailable",
        `The Arrow IPC resource returned ${response.status}.`,
        retryableResourceStatus(response.status),
      );
    }
    buffer = await response.arrayBuffer();
  } catch (cause: unknown) {
    signal?.throwIfAborted();
    if (
      cause instanceof ValueDecodeError ||
      (cause instanceof DOMException && cause.name === "AbortError")
    ) {
      throw cause;
    }
    throw new ValueDecodeError(
      "value-resource-unavailable",
      `The Arrow IPC resource could not be read: ${errorMessage(cause)}`,
      true,
    );
  }
  signal?.throwIfAborted();
  if (buffer.byteLength !== descriptor.byteLength) {
    throw new ValueDecodeError(
      "value-size-mismatch",
      `The Arrow IPC resource contained ${buffer.byteLength} bytes, expected ${descriptor.byteLength}.`,
    );
  }
  return new Uint8Array(buffer);
};

const decodeArrowValue = async (
  descriptor: ArrowValueDescriptor,
  signal?: AbortSignal,
  baseUrl?: string | URL,
): Promise<DecodedArrowValue> => {
  const bytes = await readArrowBytes(descriptor, signal, baseUrl);
  const fingerprint = await sha256Fingerprint(bytes);
  signal?.throwIfAborted();
  if (fingerprint !== undefined && fingerprint !== descriptor.fingerprint) {
    throw new ValueDecodeError(
      "value-fingerprint-mismatch",
      "The Arrow IPC resource did not match its declared fingerprint.",
    );
  }
  const { attachMarimoDataSource, tableFromIPC } = await loadArrowModule();
  signal?.throwIfAborted();
  return {
    codec: descriptor.codec,
    fingerprint: descriptor.fingerprint,
    value: attachMarimoDataSource(tableFromIPC(bytes), {
      codec: descriptor.codec,
      fingerprint: descriptor.fingerprint,
      bytes,
    }),
  };
};

const decodeValue = (
  descriptor: ValueDescriptor,
  signal?: AbortSignal,
  baseUrl?: string | URL,
): Promise<DecodedValue> => {
  if (descriptor.codec === "json-v1") {
    return Promise.resolve({
      codec: descriptor.codec,
      fingerprint: descriptor.fingerprint,
      value: descriptor.value,
    });
  }
  return decodeArrowValue(descriptor, signal, baseUrl);
};

const decodeFailure = (cause: unknown): ValueReadError =>
  cause instanceof ValueDecodeError
    ? { code: cause.code, message: cause.message }
    : {
        code: "value-decode-failed",
        message: `The projected value could not be decoded: ${errorMessage(cause)}`,
      };

const isAbort = (cause: unknown, signal?: AbortSignal): boolean =>
  signal?.aborted === true || (cause instanceof DOMException && cause.name === "AbortError");

export interface ValueDecodeOptions {
  readonly activeSelectors?: readonly string[];
  readonly baseUrl?: string | URL;
  readonly scope?: string;
  readonly signal?: AbortSignal;
}

interface CachedArrowValue {
  readonly fingerprint: string;
  readonly value: ArrowModule.MarimoArrowTable;
}

const decodeResponse = async (
  response: ValueReadResponse,
  signal?: AbortSignal,
  baseUrl?: string | URL,
  arrowValues?: Map<string, CachedArrowValue>,
): Promise<DecodedValueReadResponse> => {
  const values: Record<string, DecodedValue> = Object.create(null);
  const errors: Record<string, ValueReadError> = Object.assign(
    Object.create(null),
    response.errors,
  );
  if (Object.hasOwn(errors, "*")) {
    arrowValues?.clear();
  } else {
    Object.keys(errors).forEach((selector) => arrowValues?.delete(selector));
  }
  await Promise.all(
    Object.entries(response.values).map(async ([selector, descriptor]) => {
      if (Object.hasOwn(errors, selector)) {
        arrowValues?.delete(selector);
        return;
      }
      try {
        if (descriptor.codec === "arrow-ipc-v1") {
          const cached = arrowValues?.get(selector);
          if (cached?.fingerprint === descriptor.fingerprint) {
            values[selector] = {
              codec: descriptor.codec,
              fingerprint: descriptor.fingerprint,
              value: cached.value,
            };
            return;
          }
          arrowValues?.delete(selector);
          const decoded = await decodeArrowValue(descriptor, signal, baseUrl);
          values[selector] = decoded;
          arrowValues?.set(selector, {
            fingerprint: decoded.fingerprint,
            value: decoded.value,
          });
          return;
        }
        arrowValues?.delete(selector);
        values[selector] = await decodeValue(descriptor, signal, baseUrl);
      } catch (cause: unknown) {
        arrowValues?.delete(selector);
        if (isAbort(cause, signal) || (cause instanceof ValueDecodeError && cause.transient)) {
          throw cause;
        }
        errors[selector] = decodeFailure(cause);
      }
    }),
  );
  return { values, errors };
};

export const decodeValueReadResponse = async (
  response: ValueReadResponse,
  signal?: AbortSignal,
  baseUrl?: string | URL,
): Promise<DecodedValueReadResponse> => decodeResponse(response, signal, baseUrl);

export const createValueDecoder = () => {
  const arrowValues = new Map<string, CachedArrowValue>();
  let scope: string | undefined;

  return (response: ValueReadResponse, options: ValueDecodeOptions = {}) => {
    if (options.scope !== undefined && options.scope !== scope) {
      arrowValues.clear();
      scope = options.scope;
    }
    if (options.activeSelectors !== undefined) {
      const active = new Set(options.activeSelectors);
      for (const selector of arrowValues.keys()) {
        if (!active.has(selector)) {
          arrowValues.delete(selector);
        }
      }
    }
    return decodeResponse(response, options.signal, options.baseUrl, arrowValues);
  };
};
