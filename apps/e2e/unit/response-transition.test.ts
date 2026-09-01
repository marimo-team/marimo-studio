import { expect, test } from "vite-plus/test";

import { ResponseTransitionWindow } from "../tests/response-transition.ts";

const project = (path = "/_marimo-studio/views/dashboard/project", method = "GET") => ({
  method: () => method,
  url: () => `http://127.0.0.1:4321${path}`,
});

const transition = (limit = 64) =>
  new ResponseTransitionWindow(
    "http://127.0.0.1:4321",
    "GET",
    /^\/_marimo-studio\/views\/dashboard\/project$/,
    500,
    "configuration-error",
    200,
    limit,
  );

test("a successful response completes the direct transition contract", () => {
  const window = transition();
  const current = project();
  window.recordStart(current, {}, 1);
  window.recordResponse(current, 200, undefined);
  window.seal();

  expect(window.readyToRecover()).toBe(true);
  expect(window.recover()).toBe(true);
  expect(window.diagnostics()).toEqual([]);
});

test("one later same-owner success settles every captured failure", () => {
  const window = transition();
  const owner = {};
  const first = project();
  const second = project();
  window.recordStart(first, owner, 1);
  window.recordResponse(first, 500, "configuration-error");
  window.recordTerminal(first);
  window.recordStart(second, owner, 2);
  window.recordResponse(second, 500, "configuration-error");
  window.recordTerminal(second);
  window.seal();
  const repaired = project();
  window.recordStart(repaired, owner, 3);
  window.recordResponse(repaired, 200, undefined);
  window.recordTerminal(repaired);

  expect(window.readyToRecover()).toBe(true);
  expect(window.recover()).toBe(true);
  expect(window.diagnostics()).toEqual([]);
});

test("a foreign owner is neutral and cannot settle a captured failure", () => {
  const window = transition();
  const failedOwner = {};
  const failure = project();
  window.recordStart(failure, failedOwner, 1);
  window.recordResponse(failure, 500, "configuration-error");
  window.recordTerminal(failure);
  window.seal();
  const foreign = project();
  window.recordStart(foreign, {}, 2);
  window.recordResponse(foreign, 200, undefined);
  window.recordTerminal(foreign);

  expect(window.readyToRecover()).toBe(false);
  const repaired = project();
  window.recordStart(repaired, failedOwner, 3);
  window.recordResponse(repaired, 200, undefined);
  window.recordTerminal(repaired);
  expect(window.readyToRecover()).toBe(true);
});

test("failure after seal blocks recovery", () => {
  const window = transition();
  window.seal();
  const late = project();
  window.recordStart(late, {}, 1);
  window.recordResponse(late, 500, "configuration-error");
  window.recordTerminal(late);

  expect(window.readyToRecover()).toBe(false);
});

test("a pre-seal request may fail late and recover through a later request", () => {
  const window = transition();
  const owner = {};
  const pendingFailure = project();
  window.recordStart(pendingFailure, owner, 1);
  window.seal();
  window.recordResponse(pendingFailure, 500, "configuration-error");
  window.recordTerminal(pendingFailure);
  expect(window.readyToRecover()).toBe(false);

  const repaired = project();
  window.recordStart(repaired, owner, 2);
  window.recordResponse(repaired, 200, undefined);
  window.recordTerminal(repaired);
  expect(window.readyToRecover()).toBe(true);
  expect(window.recover()).toBe(true);
});

test("success before seal is harmless and cannot settle an earlier failure", () => {
  const window = transition();
  const owner = {};
  const failure = project();
  window.recordStart(failure, owner, 1);
  window.recordResponse(failure, 500, "configuration-error");
  window.recordTerminal(failure);
  const early = project();
  window.recordStart(early, owner, 2);
  window.recordResponse(early, 200, undefined);
  window.recordTerminal(early);
  window.seal();

  expect(window.readyToRecover()).toBe(false);
});

test("a request started before seal cannot prove later repair", () => {
  const window = transition();
  const owner = {};
  const failure = project();
  window.recordStart(failure, owner, 1);
  window.recordResponse(failure, 500, "configuration-error");
  window.recordTerminal(failure);
  const overlapping = project();
  window.recordStart(overlapping, owner, 2);
  window.seal();
  window.recordResponse(overlapping, 200, undefined);
  window.recordTerminal(overlapping);

  expect(window.readyToRecover()).toBe(false);
});

test("wrong route method error and status stay outside the transition", () => {
  const window = transition();
  expect(window.recordStart(project("/_marimo-studio/views/report/project"), {}, 1)).toBe(false);
  expect(window.recordStart(project(undefined, "POST"), {}, 2)).toBe(false);
  const wrongError = project();
  window.recordStart(wrongError, {}, 3);
  expect(window.recordResponse(wrongError, 500, "other-error")).toBe(false);
  window.recordTerminal(wrongError);
  const wrongStatus = project();
  window.recordStart(wrongStatus, {}, 4);
  expect(window.recordResponse(wrongStatus, 409, "configuration-error")).toBe(false);
  window.recordTerminal(wrongStatus);
});

test("pending requests block recovery", () => {
  const window = transition();
  const owner = {};
  const pending = project();
  window.recordStart(pending, owner, 1);
  window.seal();

  expect(window.readyToRecover()).toBe(false);
});

test("overflow stops retaining new failure owners", () => {
  const window = transition(1);
  const firstOwner = {};
  const first = project();
  window.recordStart(first, firstOwner, 1);
  window.recordResponse(first, 500, "configuration-error");
  window.recordTerminal(first);
  const extra = project();
  window.recordStart(extra, {}, 2);
  window.recordResponse(extra, 500, "configuration-error");
  window.recordTerminal(extra);
  window.seal();
  const repaired = project();
  window.recordStart(repaired, firstOwner, 3);
  window.recordResponse(repaired, 200, undefined);

  expect(window.readyToRecover()).toBe(false);
});
