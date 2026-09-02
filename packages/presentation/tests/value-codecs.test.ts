import { getMarimoDataSource } from "@marimo-studio/marimo-frontend/arrow-table";
import { afterEach, expect, test, vi } from "vite-plus/test";

import { createValueDecoder, decodeValueReadResponse } from "../src/values/codecs.ts";
import { ARROW_FINGERPRINT, arrowBytes } from "./arrow-fixture.ts";

afterEach(() => {
  vi.unstubAllGlobals();
});

const requestUrl = (input: RequestInfo | URL): string => {
  if (input instanceof Request) {
    return input.url;
  }
  return new URL(input, "http://localhost").href;
};

test("JSON values decode without loading a resource", async () => {
  const fetch = vi.fn(() => Promise.reject(new Error("unexpected fetch")));
  vi.stubGlobal("fetch", fetch);

  const decoded = await decodeValueReadResponse({
    values: {
      report: {
        codec: "json-v1",
        fingerprint: `sha256:${"0".repeat(64)}`,
        value: { total: 42 },
      },
    },
    errors: {},
  });

  expect(decoded.values.report).toEqual({
    codec: "json-v1",
    fingerprint: `sha256:${"0".repeat(64)}`,
    value: { total: 42 },
  });
  expect(fetch).not.toHaveBeenCalled();
});

test("Arrow values expose one verified Flechette table and its source bytes", async () => {
  const bytes = arrowBytes();
  const fetchedBuffer = bytes.buffer;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      const response = new Response();
      response.arrayBuffer = async () => fetchedBuffer;
      return response;
    }),
  );

  const decoded = await decodeValueReadResponse({
    values: {
      frame: {
        codec: "arrow-ipc-v1",
        fingerprint: ARROW_FINGERPRINT,
        dataUrl: "/@file/frame.arrow",
        byteLength: bytes.byteLength,
      },
    },
    errors: {},
  });
  const projected = decoded.values.frame;
  expect(projected?.codec).toBe("arrow-ipc-v1");
  if (projected?.codec !== "arrow-ipc-v1") {
    throw new Error("Expected an Arrow value");
  }
  const frame = projected.value;

  expect(frame).toMatchObject({ numCols: 2, numRows: 2, names: ["city", "score"] });
  expect(frame.get(0)).toEqual({ city: "Budapest", score: 7 });

  const source = getMarimoDataSource(frame);
  expect(source).toMatchObject({
    codec: "arrow-ipc-v1",
    fingerprint: ARROW_FINGERPRINT,
  });
  expect(source?.bytes.byteLength).toBe(bytes.byteLength);
  expect(source?.bytes.buffer).toBe(fetchedBuffer);
  expect(getMarimoDataSource(null)).toBeUndefined();
});

test("Arrow cache follows fingerprints, selector ownership, and projection scope", async () => {
  const bytes = arrowBytes();
  const fetch = vi.fn(async () => new Response(bytes.buffer));
  vi.stubGlobal("fetch", fetch);
  const decode = createValueDecoder();
  const response = {
    values: {
      frame: {
        codec: "arrow-ipc-v1" as const,
        fingerprint: ARROW_FINGERPRINT,
        dataUrl: "/@file/frame.arrow",
        byteLength: bytes.byteLength,
      },
    },
    errors: {},
  };

  const revisionOne = { activeSelectors: ["frame"], scope: "revision-1" };
  const first = await decode(response, revisionOne);
  const second = await decode(response, revisionOne);
  expect(second.values.frame?.value).toBe(first.values.frame?.value);
  expect(fetch).toHaveBeenCalledTimes(1);

  const failed = await decode(
    {
      values: {
        frame: {
          ...response.values.frame,
          fingerprint: `sha256:${"1".repeat(64)}`,
        },
      },
      errors: {},
    },
    revisionOne,
  );
  const recovered = await decode(response, revisionOne);

  expect(failed.values.frame).toBeUndefined();
  expect(failed.errors.frame?.code).toBe("value-fingerprint-mismatch");
  expect(recovered.values.frame?.value).not.toBe(first.values.frame?.value);

  await decode({ values: {}, errors: {} }, { activeSelectors: [], scope: "revision-1" });
  const reacquired = await decode(response, revisionOne);
  expect(reacquired.values.frame?.value).not.toBe(recovered.values.frame?.value);

  const nextRevision = await decode(response, {
    activeSelectors: ["frame"],
    scope: "revision-2",
  });
  expect(nextRevision.values.frame?.value).not.toBe(reacquired.values.frame?.value);
});

test("Arrow resource failures remain transient read failures", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(null, { status: 503 })),
  );

  await expect(
    decodeValueReadResponse({
      values: {
        frame: {
          codec: "arrow-ipc-v1",
          fingerprint: ARROW_FINGERPRINT,
          dataUrl: "/@file/frame.arrow",
          byteLength: arrowBytes().byteLength,
        },
      },
      errors: {},
    }),
  ).rejects.toMatchObject({
    code: "value-resource-unavailable",
    transient: true,
  });
});

test("Arrow authorization failures stay terminal and selector-local", async () => {
  const fetch = vi.fn(async () => new Response(null, { status: 403 }));
  vi.stubGlobal("fetch", fetch);

  const decoded = await decodeValueReadResponse({
    values: {
      frame: {
        codec: "arrow-ipc-v1",
        fingerprint: ARROW_FINGERPRINT,
        dataUrl: "/@file/frame.arrow",
        byteLength: arrowBytes().byteLength,
      },
    },
    errors: {},
  });

  expect(decoded.errors.frame?.code).toBe("value-resource-unavailable");
});

test("Arrow decoding remains available when SubtleCrypto is unavailable", async () => {
  const bytes = arrowBytes();
  vi.stubGlobal("crypto", {});
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(bytes.buffer)),
  );

  const decoded = await decodeValueReadResponse({
    values: {
      frame: {
        codec: "arrow-ipc-v1",
        fingerprint: `sha256:${"0".repeat(64)}`,
        dataUrl: "/@file/frame.arrow",
        byteLength: bytes.byteLength,
      },
    },
    errors: {},
  });

  expect(decoded.values.frame?.codec).toBe("arrow-ipc-v1");
  expect(decoded.errors.frame).toBeUndefined();
});

test("Arrow verification failures stay local to their selectors", async () => {
  const bytes = arrowBytes();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      const body = url.endsWith("corrupt.arrow") ? new Uint8Array([1, 2, 3, 4]) : bytes;
      return Promise.resolve(new Response(body.buffer));
    }),
  );

  const corruptFingerprint = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new Uint8Array([1, 2, 3, 4]),
  );
  const corruptHex = Array.from(new Uint8Array(corruptFingerprint), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
  const decoded = await decodeValueReadResponse({
    values: {
      good: {
        codec: "json-v1",
        fingerprint: `sha256:${"0".repeat(64)}`,
        value: 42,
      },
      mismatch: {
        codec: "arrow-ipc-v1",
        fingerprint: `sha256:${"1".repeat(64)}`,
        dataUrl: "/mismatch.arrow",
        byteLength: bytes.byteLength,
      },
      wrongSize: {
        codec: "arrow-ipc-v1",
        fingerprint: ARROW_FINGERPRINT,
        dataUrl: "/wrong-size.arrow",
        byteLength: bytes.byteLength - 1,
      },
      corrupt: {
        codec: "arrow-ipc-v1",
        fingerprint: `sha256:${corruptHex}`,
        dataUrl: "/corrupt.arrow",
        byteLength: 4,
      },
      oversized: {
        codec: "arrow-ipc-v1",
        fingerprint: `sha256:${"2".repeat(64)}`,
        dataUrl: "/oversized.arrow",
        byteLength: 1_000_001,
      },
    },
    errors: {},
  });

  expect(decoded.values.good?.value).toBe(42);
  expect(decoded.errors.mismatch?.code).toBe("value-fingerprint-mismatch");
  expect(decoded.errors.wrongSize?.code).toBe("value-size-mismatch");
  expect(decoded.errors.corrupt?.code).toBe("value-decode-failed");
  expect(decoded.errors.oversized?.code).toBe("value-too-large");
});

test("aborting an Arrow resource read aborts the value read", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      (_input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener(
            "abort",
            () => reject(new DOMException("cancelled", "AbortError")),
            { once: true },
          );
        }),
    ),
  );
  const controller = new AbortController();
  const reading = decodeValueReadResponse(
    {
      values: {
        frame: {
          codec: "arrow-ipc-v1",
          fingerprint: ARROW_FINGERPRINT,
          dataUrl: "/frame.arrow",
          byteLength: arrowBytes().byteLength,
        },
      },
      errors: {},
    },
    controller.signal,
  );

  controller.abort();

  await expect(reading).rejects.toMatchObject({ name: "AbortError" });
});
