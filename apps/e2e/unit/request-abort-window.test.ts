import { expect, test } from "vite-plus/test";

import { ExactRequestAbortWindow } from "../tests/request-abort-window.ts";

const request = (method: string, path: string) => ({
  method: () => method,
  postData: () => null,
  resourceType: () => "fetch",
  url: () => `http://127.0.0.1:4321${path}`,
});

const queryWrite = () => request("POST", "/_marimo-studio/query");

test("a backfilled request retains its response status and exact object identity", () => {
  const window = new ExactRequestAbortWindow(
    "POST",
    "http://127.0.0.1:4321",
    /^\/_marimo-studio\/query$/,
    1,
    true,
    202,
  );
  const bound = queryWrite();

  expect(window.recordActive(bound, 202)).toBe(true);
  expect(window.recordAbort(queryWrite(), "net::ERR_ABORTED")).toBe(false);
  expect(window.recordAbort(bound, "net::ERR_ABORTED")).toBe(true);
  window.seal();
  expect(window.readyToRecover()).toBe(true);
  expect(window.recover()).toBe(true);
  expect(window.diagnostics()).toEqual([]);
});

test("an abort with the wrong response status fails closed", () => {
  const window = new ExactRequestAbortWindow(
    "POST",
    "http://127.0.0.1:4321",
    /^\/_marimo-studio\/query$/,
    1,
    true,
    202,
  );
  const conflict = queryWrite();
  window.recordActive(conflict, 409);
  window.recordAbort(conflict, "net::ERR_ABORTED");
  window.seal();

  expect(window.readyToRecover()).toBe(false);
  expect(window.recover()).toBe(false);
});

test("a sealed window becomes ready when abort and status arrive after user completion", () => {
  const window = new ExactRequestAbortWindow(
    "POST",
    "http://127.0.0.1:4321",
    /^\/_marimo-studio\/query$/,
    1,
    true,
    202,
  );
  const pending = request("POST", "/_marimo-studio/query");
  window.recordStart(pending);
  window.seal();
  expect(window.readyToRecover()).toBe(false);

  window.recordAbort(pending, "net::ERR_ABORTED");
  expect(window.readyToRecover()).toBe(false);
  window.recordResponse(pending, 202);
  expect(window.readyToRecover()).toBe(true);
  expect(window.recover()).toBe(true);
  expect(window.diagnostics()).toEqual([]);
});

test("recovery before a required request starts fails closed", () => {
  const window = new ExactRequestAbortWindow(
    "POST",
    "http://127.0.0.1:4321",
    /^\/_marimo-studio\/query$/,
  );

  expect(window.recover()).toBe(false);
  const late = request("POST", "/_marimo-studio/query");
  expect(window.recordStart(late)).toBe(false);
});

test("a required window ignores a successful retry after its exact abort", () => {
  const window = new ExactRequestAbortWindow(
    "POST",
    "http://127.0.0.1:4321",
    /^\/_marimo-studio\/activations\/\d+\/ack$/,
  );
  const timedOut = request("POST", "/_marimo-studio/activations/1/ack");
  const retry = request("POST", "/_marimo-studio/activations/1/ack");

  window.recordStart(timedOut);
  window.recordAbort(timedOut, "net::ERR_ABORTED");
  window.recordStart(retry);
  window.recordTerminal(retry);
  window.seal();
  expect(window.readyToRecover()).toBe(true);
  expect(window.recover()).toBe(true);
  expect(window.diagnostics()).toEqual([]);
});

test("a required window rejects an abort beyond its cardinality", () => {
  const window = new ExactRequestAbortWindow(
    "POST",
    "http://127.0.0.1:4321",
    /^\/_marimo-studio\/query$/,
  );
  const first = queryWrite();
  const extra = queryWrite();
  window.recordStart(first);
  window.recordAbort(first, "net::ERR_ABORTED");
  window.recordStart(extra);
  window.recordAbort(extra, "net::ERR_ABORTED");
  window.seal();

  expect(window.readyToRecover()).toBe(false);
  expect(window.recover()).toBe(false);
});

test("an optional active window removes a normally completed candidate", () => {
  const window = new ExactRequestAbortWindow(
    "GET",
    "http://127.0.0.1:4321",
    /^\/_marimo-studio\/presentation\/[^/]+\/dashboard\/$/,
    1,
    false,
  );
  const active = request("GET", "/_marimo-studio/presentation/d.token/dashboard/");
  window.recordActive(active, 200);
  window.seal();
  window.recordTerminal(active);

  expect(window.readyToRecover()).toBe(true);
  expect(window.recover()).toBe(true);
  expect(window.diagnostics()).toEqual([]);
});

test("an optional active window accepts its concrete old-request abort", () => {
  const window = new ExactRequestAbortWindow(
    "GET",
    "http://127.0.0.1:4321",
    /^\/_marimo-studio\/presentation\/[^/]+\/dashboard\/$/,
    1,
    false,
    200,
  );
  const active = request("GET", "/_marimo-studio/presentation/d.token/dashboard/");
  window.recordActive(active, 200);
  window.seal();
  window.recordAbort(active, "net::ERR_ABORTED");

  expect(window.readyToRecover()).toBe(true);
  expect(window.recover()).toBe(true);
  expect(window.diagnostics()).toEqual([]);
});

test("a required active window owns one live stream and rejects its successor", () => {
  const window = new ExactRequestAbortWindow(
    "GET",
    "http://127.0.0.1:4321",
    /^\/_marimo-studio\/presentation\/[^/]+\/_marimo-studio\/dev\/events$/,
    1,
    true,
  );
  const current = request(
    "GET",
    "/_marimo-studio/presentation/r.current/_marimo-studio/dev/events",
  );
  const successor = request("GET", "/_marimo-studio/presentation/r.next/_marimo-studio/dev/events");
  window.recordStart(current);
  window.seal();
  expect(window.recordStart(successor)).toBe(false);
  expect(window.recordAbort(current, "net::ERR_ABORTED")).toBe(true);

  expect(window.readyToRecover()).toBe(true);
  expect(window.recover()).toBe(true);
  expect(window.diagnostics()).toEqual([]);
});

test("an optional future window ignores success and counts one later abort", () => {
  const window = new ExactRequestAbortWindow(
    "GET",
    "http://127.0.0.1:4321",
    /^\/_marimo-studio\/presentation\/[^/]+\/dashboard\/$/,
    1,
    false,
  );
  const completed = request("GET", "/_marimo-studio/presentation/d.first/dashboard/");
  const aborted = request("GET", "/_marimo-studio/presentation/d.second/dashboard/");
  window.recordStart(completed);
  window.recordTerminal(completed);
  window.recordStart(aborted);
  window.recordAbort(aborted, "net::ERR_ABORTED");
  window.seal();

  expect(window.readyToRecover()).toBe(true);
  expect(window.recover()).toBe(true);
  expect(window.diagnostics()).toEqual([]);
});

test("an unresolved active candidate blocks recovery", () => {
  const window = new ExactRequestAbortWindow(
    "GET",
    "http://127.0.0.1:4321",
    /^\/_marimo-studio\/presentation\/[^/]+\/dashboard\/$/,
    1,
    false,
  );
  window.recordStart(request("GET", "/_marimo-studio/presentation/d.active/dashboard/"));
  window.seal();

  expect(window.readyToRecover()).toBe(false);
  expect(window.recover()).toBe(false);
});

test("an optional active window never claims a future request", () => {
  const window = new ExactRequestAbortWindow(
    "GET",
    "http://127.0.0.1:4321",
    /^\/_marimo-studio\/presentation\/[^/]+\/dashboard\/$/,
    1,
    false,
  );
  window.seal();
  const future = request("GET", "/_marimo-studio/presentation/d.token/dashboard/");

  expect(window.recordStart(future)).toBe(false);
  expect(window.recordAbort(future, "net::ERR_ABORTED")).toBe(false);
  expect(window.readyToRecover()).toBe(true);
  expect(window.recover()).toBe(true);
});
