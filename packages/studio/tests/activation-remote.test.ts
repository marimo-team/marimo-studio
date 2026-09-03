import { afterEach, expect, it, vi } from "vite-plus/test";

import type { JsonFetch } from "./agent-remote-test-support.ts";

import {
  createViewActivationRemote,
  ViewActivationAcknowledgementError,
} from "../src/app/activation-remote.ts";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("acknowledges an activation with its browser identity", async () => {
  const fetch = vi.fn<JsonFetch>(async () =>
    Response.json({ schema: 1, outcome: "applied" }, { status: 200 }),
  );
  vi.stubGlobal("fetch", fetch);
  const acknowledge = createViewActivationRemote(
    "/_marimo-studio",
    "server-token",
    "browser-client-1234",
  );

  await acknowledge({ schema: 1, generation: 9, view: "report" }, new AbortController().signal);

  expect(fetch).toHaveBeenCalledWith(
    expect.stringContaining("/_marimo-studio/activations/9/ack"),
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        schema: 1,
        clientId: "browser-client-1234",
        view: "report",
      }),
    }),
  );
});

it("binds an activation acknowledgement to its observed view owner", async () => {
  const fetch = vi.fn<JsonFetch>(async () =>
    Response.json({ schema: 1, outcome: "applied" }, { status: 200 }),
  );
  vi.stubGlobal("fetch", fetch);
  const acknowledge = createViewActivationRemote(
    "/_marimo-studio",
    "server-token",
    "browser-client-1234",
  );

  await acknowledge(
    {
      schema: 1,
      generation: 10,
      view: "report",
      owner: {
        kind: "present",
        catalogGeneration: "a".repeat(64),
        viewGeneration: "b".repeat(64),
      },
    },
    new AbortController().signal,
  );

  expect(fetch).toHaveBeenCalledWith(
    expect.stringContaining("/_marimo-studio/activations/10/ack"),
    expect.objectContaining({
      body: JSON.stringify({
        schema: 1,
        clientId: "browser-client-1234",
        view: "report",
        catalogGeneration: "a".repeat(64),
        viewGeneration: "b".repeat(64),
      }),
    }),
  );
});

it("acknowledges a catalog-owned absent view name", async () => {
  const fetch = vi.fn<JsonFetch>(async () =>
    Response.json({ schema: 1, outcome: "applied" }, { status: 200 }),
  );
  vi.stubGlobal("fetch", fetch);
  const acknowledge = createViewActivationRemote(
    "/_marimo-studio",
    "server-token",
    "browser-client-1234",
  );

  await acknowledge(
    {
      schema: 1,
      generation: 11,
      view: "report",
      owner: { kind: "absent", catalogGeneration: "a".repeat(64) },
    },
    new AbortController().signal,
  );

  expect(fetch).toHaveBeenCalledWith(
    expect.stringContaining("/_marimo-studio/activations/11/ack"),
    expect.objectContaining({
      body: JSON.stringify({
        schema: 1,
        clientId: "browser-client-1234",
        view: "report",
        catalogGeneration: "a".repeat(64),
        viewGeneration: null,
      }),
    }),
  );
});

it("retries when an activation acknowledgement body stalls", async () => {
  vi.useFakeTimers();
  const fetch = vi.fn<JsonFetch>((_url, init) => {
    if (fetch.mock.calls.length === 1) {
      // SAFETY: The test response implements the Response members consumed by
      // the acknowledgement boundary and controls its body promise explicitly.
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener("abort", () =>
              reject(new DOMException("Aborted", "AbortError")),
            );
          }),
      } as Response);
    }
    return Promise.resolve(Response.json({ schema: 1, outcome: "applied" }, { status: 200 }));
  });
  vi.stubGlobal("fetch", fetch);
  const acknowledge = createViewActivationRemote(
    "/_marimo-studio",
    "server-token",
    "browser-client-1234",
  );

  const owner = new AbortController();
  const acknowledged = acknowledge({ schema: 1, generation: 11, view: "report" }, owner.signal);
  await vi.waitFor(() => expect(fetch).toHaveBeenCalledOnce());
  await vi.advanceTimersByTimeAsync(10_100);
  await acknowledged;

  expect(fetch).toHaveBeenCalledTimes(2);
  expect(fetch.mock.calls[0]?.[1].signal?.aborted).toBe(true);
  expect(fetch.mock.calls[1]?.[1].signal?.aborted).toBe(false);
  expect(owner.signal.aborted).toBe(false);
  expect(fetch.mock.calls[0]?.[0]).toContain("/_marimo-studio/activations/11/ack");
});

it("retries an activation acknowledgement while the browser binding settles", async () => {
  vi.useFakeTimers();
  const fetch = vi.fn<JsonFetch>();
  fetch.mockResolvedValueOnce(Response.json({ schema: 1, outcome: "retryable" }, { status: 202 }));
  fetch.mockResolvedValueOnce(Response.json({ schema: 1, outcome: "applied" }, { status: 200 }));
  vi.stubGlobal("fetch", fetch);
  const acknowledge = createViewActivationRemote(
    "/_marimo-studio",
    "server-token",
    "browser-client-1234",
  );

  const acknowledged = acknowledge(
    { schema: 1, generation: 12, view: "report" },
    new AbortController().signal,
  );
  await vi.advanceTimersByTimeAsync(100);
  await acknowledged;

  expect(fetch).toHaveBeenCalledTimes(2);
});

it("does not retry a rejected activation acknowledgement", async () => {
  const fetch = vi.fn<JsonFetch>(async () =>
    Response.json({ schema: 1, outcome: "rejected" }, { status: 409 }),
  );
  vi.stubGlobal("fetch", fetch);
  const acknowledge = createViewActivationRemote(
    "/_marimo-studio",
    "server-token",
    "browser-client-1234",
  );

  await expect(
    acknowledge({ schema: 1, generation: 13, view: "report" }, new AbortController().signal),
  ).rejects.toMatchObject({ outcome: "rejected" });

  expect(fetch).toHaveBeenCalledOnce();
});

it("reports uncertainty when every acknowledgement response is lost", async () => {
  vi.useFakeTimers();
  const fetch = vi.fn<JsonFetch>(async () => {
    throw new TypeError("connection closed before the response arrived");
  });
  vi.stubGlobal("fetch", fetch);
  const acknowledge = createViewActivationRemote(
    "/_marimo-studio",
    "server-token",
    "browser-client-1234",
  );

  const result = acknowledge(
    { schema: 1, generation: 14, view: "report" },
    new AbortController().signal,
  );
  const rejected = expect(result).rejects.toBeInstanceOf(ViewActivationAcknowledgementError);
  await vi.runAllTimersAsync();
  await rejected;
  await expect(result).rejects.toMatchObject({ outcome: "uncertain" });
  expect(fetch).toHaveBeenCalledTimes(3);
});
