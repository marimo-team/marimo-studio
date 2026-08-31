import { expect, test } from "vite-plus/test";

import {
  BrowserRequestOwners,
  abortedResponseCompleted,
  browserRequestIdentity,
  ExactRequestAbortWitness,
  IdempotentReadRecovery,
  WorkspaceEventStreamReplacementWindow,
  isIdempotentReadRequest,
  requestAbortsRetiredByDocument,
} from "../tests/request-identity.ts";

interface RequestOptions {
  method?: string;
  postData?: string | null;
  resourceType?: string;
  url?: string;
}

const request = ({
  method = "GET",
  postData = null,
  resourceType = "fetch",
  url = "http://127.0.0.1:4321/_marimo-studio/views/dashboard/config?runtime=server",
}: RequestOptions = {}) => ({
  method: () => method,
  postData: () => postData,
  resourceType: () => resourceType,
  url: () => url,
});

const workspaceEventRequest = (
  generation: number,
  options: Pick<RequestOptions, "method" | "resourceType" | "url"> = {},
) =>
  request({
    method: options.method ?? "GET",
    resourceType: options.resourceType ?? "eventsource",
    url:
      options.url ??
      `http://127.0.0.1:4321/_marimo-studio/dev/events?marimo_studio_connection=${generation}&marimo_studio_view=dashboard`,
  });

const presentationDocument = (revision: string, view = "dashboard", lifecycle = 1) =>
  request({
    resourceType: "document",
    url: `http://127.0.0.1:4321/_marimo-studio/presentation/${revision}/${view}/?file=notebook.py&marimo_studio_lifecycle=${lifecycle}&session_id=session-${lifecycle}`,
  });

const directRenewalDocument = (renewal: string, lifecycle: number) =>
  request({
    resourceType: "document",
    url: `http://127.0.0.1:4321/dashboard/?file=notebook.py&marimo_studio_renewal=${renewal}&marimo_studio_lifecycle=${lifecycle}&session_id=session-${lifecycle}`,
  });

test("reuses one browser request owner for each source", () => {
  const owners = new BrowserRequestOwners<object>();
  const frame = {};
  expect(owners.ownerFor(frame)).toBe(owners.ownerFor(frame));
});

test("keeps browser request owners isolated by source", () => {
  const owners = new BrowserRequestOwners<object>();
  expect(owners.ownerFor({})).not.toBe(owners.ownerFor({}));
});

test("a completed document retires only earlier aborts from its frame owner", () => {
  const owner = { id: 1 };
  const otherOwner = { id: 2 };
  const retiredDocument = request();
  const retiredAsset = request();
  const laterFailure = request();
  const otherFrameFailure = request();
  const missingStart = request();

  expect(
    requestAbortsRetiredByDocument(
      [
        { owner, request: retiredDocument, start: 1 },
        { owner, request: retiredAsset, start: 2 },
        { owner, request: laterFailure, start: 4 },
        { owner: otherOwner, request: otherFrameFailure, start: 1 },
        { owner, request: missingStart, start: undefined },
      ],
      owner,
      3,
    ).map(({ request: retired }) => retired),
  ).toEqual([retiredDocument, retiredAsset]);
});

test("accepts one future abort from the exact held request after completion", async () => {
  let complete!: () => void;
  const completion = new Promise<void>((resolve) => {
    complete = resolve;
  });
  const held = request();
  const witness = new ExactRequestAbortWitness(held, completion);

  expect(witness.recordFailure(request(), "net::ERR_ABORTED")).toBe(false);
  expect(witness.recordFailure(held, "net::ERR_FAILED")).toBe(false);
  expect(witness.recordFailure(held, "net::ERR_ABORTED")).toBe(true);
  await witness.waitForAbort();
  complete();
  await completion;

  expect(witness.recover()).toBe(true);
  expect(witness.diagnostics()).toEqual([]);
});

test("held request abort recovery fails closed before route completion", () => {
  const held = request();
  const witness = new ExactRequestAbortWitness(held, new Promise<void>(() => {}));

  expect(witness.recordFailure(held, "net::ERR_ABORTED")).toBe(true);
  expect(witness.recover()).toBe(false);
  expect(witness.diagnostics()).toContain(
    "exact held request abort recovered before request completion",
  );
});

test("a completed held request still requires its exact abort", async () => {
  const witness = new ExactRequestAbortWitness(request(), Promise.resolve());
  await Promise.resolve();

  expect(witness.recover()).toBe(false);
  expect(witness.diagnostics()).toContain("expected exact held request abort, saw none");
});

test("binds abort recovery to the complete browser operation identity", () => {
  const original = browserRequestIdentity(request());
  expect(browserRequestIdentity(request())).toBe(original);
  expect(
    browserRequestIdentity(
      request({
        url: "http://127.0.0.1:4321/_marimo-studio/views/dashboard/config?runtime=wasm",
      }),
    ),
  ).not.toBe(original);
  expect(browserRequestIdentity(request({ postData: '{"revision":"next"}' }))).not.toBe(original);
  expect(browserRequestIdentity(request({ resourceType: "eventsource" }))).not.toBe(original);
});

test("requires body completion before accepting an aborted document response", () => {
  expect(abortedResponseCompleted(request({ resourceType: "document" }), 200)).toBe(false);
  expect(abortedResponseCompleted(request({ resourceType: "document" }), 200, true)).toBe(true);
  expect(abortedResponseCompleted(request({ resourceType: "document" }), 500)).toBe(false);
  expect(abortedResponseCompleted(request(), 200)).toBe(false);
  expect(abortedResponseCompleted(request(), 204)).toBe(true);
  expect(abortedResponseCompleted(request({ method: "HEAD" }), 304)).toBe(true);
  expect(abortedResponseCompleted(request({ method: "POST", resourceType: "document" }), 200)).toBe(
    false,
  );
});

test("accepts completed presentation readiness probes only at their 202 boundary", () => {
  const probe = request({
    resourceType: "fetch",
    url: "http://127.0.0.1:4321/_marimo-studio/presentation/d.revision/dashboard/?file=notebook.py",
  });
  expect(abortedResponseCompleted(probe, 202)).toBe(false);
  expect(abortedResponseCompleted(probe, 202, true)).toBe(true);
  expect(abortedResponseCompleted(probe, 200)).toBe(false);
  expect(
    abortedResponseCompleted(
      request({ resourceType: "fetch", url: "http://127.0.0.1:4321/other-poll" }),
      202,
    ),
  ).toBe(false);
});

test("concurrent success before abort event order recovers one abort", () => {
  const recovery = new IdempotentReadRecovery();
  const frame = { id: 1 };
  const aborted = request();
  const retry = request();
  recovery.recordStart(aborted, frame);
  recovery.recordStart(retry, frame);
  expect(recovery.recordSuccess(retry)).toBeUndefined();
  expect(recovery.recordAbort(aborted)).toBe(true);
});

test("concurrent abort before success event order recovers one abort", () => {
  const recovery = new IdempotentReadRecovery();
  const frame = { id: 1 };
  const aborted = request();
  const retry = request();
  const abortStart = recovery.recordStart(aborted, frame);
  recovery.recordStart(retry, frame);
  expect(recovery.recordAbort(aborted)).toBe(false);
  expect(recovery.recordSuccess(retry)).toBe(abortStart);
});

test("a concurrent presentation revision recovers one abort in the same frame", () => {
  const recovery = new IdempotentReadRecovery();
  const owner = { id: 1 };
  const aborted = presentationDocument("d.first", "dashboard", 1);
  const successor = presentationDocument("d.second", "dashboard", 2);
  recovery.recordStart(aborted, owner);
  recovery.recordStart(successor, owner);

  expect(recovery.recordSuccess(successor)).toBeUndefined();
  expect(recovery.recordAbort(aborted)).toBe(true);
});

test("presentation recovery stays bound to its view and frame owner", () => {
  const recovery = new IdempotentReadRecovery();
  const aborted = presentationDocument("d.first", "dashboard", 1);
  const otherView = presentationDocument("d.second", "report", 2);
  const otherOwner = presentationDocument("d.third", "dashboard", 3);
  recovery.recordStart(aborted, { id: 1 });
  recovery.recordStart(otherView, { id: 1 });
  recovery.recordStart(otherOwner, { id: 2 });

  expect(recovery.recordSuccess(otherView)).toBeUndefined();
  expect(recovery.recordSuccess(otherOwner)).toBeUndefined();
  expect(recovery.recordAbort(aborted)).toBe(false);
});

test("a later presentation successor recovers an earlier abort", () => {
  const recovery = new IdempotentReadRecovery();
  const owner = { id: 1 };
  const aborted = presentationDocument("d.first", "dashboard", 1);
  const abortStart = recovery.recordStart(aborted, owner);
  expect(recovery.recordAbort(aborted)).toBe(false);

  const successor = presentationDocument("d.second", "dashboard", 2);
  recovery.recordStart(successor, owner);
  expect(recovery.recordSuccess(successor)).toBe(abortStart);
});

test("a direct renewal document recovers through its later successor", () => {
  const recovery = new IdempotentReadRecovery();
  const owner = { id: 1 };
  const aborted = directRenewalDocument("d.first", 1);
  const abortStart = recovery.recordStart(aborted, owner);
  expect(recovery.recordAbort(aborted)).toBe(false);

  const successor = directRenewalDocument("d.second", 2);
  recovery.recordStart(successor, owner);
  expect(recovery.recordSuccess(successor)).toBe(abortStart);
});

test("a direct renewal succeeds an aborted revision document", () => {
  const recovery = new IdempotentReadRecovery();
  const owner = { id: 1 };
  const aborted = presentationDocument("d.first", "dashboard", 1);
  const abortStart = recovery.recordStart(aborted, owner);
  expect(recovery.recordAbort(aborted)).toBe(false);

  const successor = directRenewalDocument("d.second", 2);
  recovery.recordStart(successor, owner);
  expect(recovery.recordSuccess(successor)).toBe(abortStart);
});

test("a completed generation cannot recover a later sequential abort", () => {
  const recovery = new IdempotentReadRecovery();
  const frame = { id: 1 };
  const completed = request();
  const aborted = request();
  recovery.recordStart(completed, frame);
  expect(recovery.recordSuccess(completed)).toBeUndefined();
  recovery.recordStart(aborted, frame);
  expect(recovery.recordAbort(aborted)).toBe(false);
});

test("an earlier concurrent read success cannot recover a later read abort", () => {
  const recovery = new IdempotentReadRecovery();
  const owner = { id: 1 };
  const completed = request();
  const aborted = request();
  recovery.recordStart(completed, owner);
  recovery.recordStart(aborted, owner);
  expect(recovery.recordSuccess(completed)).toBeUndefined();
  expect(recovery.recordAbort(aborted)).toBe(false);
});

test("out-of-order terminals pair each abort with its nearest newer success", () => {
  const recovery = new IdempotentReadRecovery();
  const owner = { id: 1 };
  const firstAbort = request();
  const firstSuccess = request();
  const secondAbort = request();
  const secondSuccess = request();
  for (const operation of [firstAbort, firstSuccess, secondAbort, secondSuccess]) {
    recovery.recordStart(operation, owner);
  }

  recovery.recordSuccess(secondSuccess);
  recovery.recordSuccess(firstSuccess);
  expect(recovery.recordAbort(firstAbort)).toBe(true);
  expect(recovery.recordAbort(secondAbort)).toBe(true);
});

test("two concurrent aborts and one success leave one abort unmatched", () => {
  const recovery = new IdempotentReadRecovery();
  const frame = { id: 1 };
  const firstAbort = request();
  const secondAbort = request();
  const retry = request();
  recovery.recordStart(firstAbort, frame);
  recovery.recordStart(secondAbort, frame);
  recovery.recordStart(retry, frame);
  expect(recovery.recordSuccess(retry)).toBeUndefined();
  expect(recovery.recordAbort(firstAbort)).toBe(true);
  expect(recovery.recordAbort(secondAbort)).toBe(false);
});

test("a different browser operation cannot recover an abort", () => {
  const recovery = new IdempotentReadRecovery();
  const frame = { id: 1 };
  const aborted = request({ postData: '{"projection":"summary"}' });
  const completed = request({ postData: '{"projection":"table"}' });
  recovery.recordStart(aborted, frame);
  recovery.recordStart(completed, frame);
  expect(recovery.recordSuccess(completed)).toBeUndefined();
  expect(recovery.recordAbort(aborted)).toBe(false);
});

test("bounds retained browser operation success credits", () => {
  const recovery = new IdempotentReadRecovery(2);
  const frame = { id: 1 };
  const firstAbort = request();
  const secondAbort = request();
  const thirdAbort = request();
  const firstSuccess = request();
  const secondSuccess = request();
  const thirdSuccess = request();
  for (const operation of [
    firstAbort,
    secondAbort,
    thirdAbort,
    firstSuccess,
    secondSuccess,
    thirdSuccess,
  ]) {
    recovery.recordStart(operation, frame);
  }
  recovery.recordSuccess(firstSuccess);
  recovery.recordSuccess(secondSuccess);
  recovery.recordSuccess(thirdSuccess);
  expect(recovery.recordAbort(firstAbort)).toBe(true);
  expect(recovery.recordAbort(secondAbort)).toBe(true);
  expect(recovery.recordAbort(thirdAbort)).toBe(false);
});

test("listener teardown closes an in-flight overlap generation", () => {
  const recovery = new IdempotentReadRecovery();
  const frame = { id: 1 };
  const abandoned = request();
  recovery.recordStart(abandoned, frame);
  recovery.recordFailure(abandoned);
  const completed = request();
  recovery.recordStart(completed, frame);
  expect(recovery.recordSuccess(completed)).toBeUndefined();
  const laterAbort = request();
  recovery.recordStart(laterAbort, frame);
  expect(recovery.recordAbort(laterAbort)).toBe(false);
});

test("identical operations in separate frames never recover each other", () => {
  const recovery = new IdempotentReadRecovery();
  const completed = request();
  const aborted = request();
  recovery.recordStart(completed, { id: 1 });
  recovery.recordStart(aborted, { id: 2 });
  expect(recovery.recordSuccess(completed)).toBeUndefined();
  expect(recovery.recordAbort(aborted)).toBe(false);
});

test("an overlapping successful POST never recovers an aborted POST", () => {
  const recovery = new IdempotentReadRecovery();
  const owner = { id: 1 };
  const aborted = request({ method: "POST", postData: '{"revision":"same"}' });
  const completed = request({ method: "POST", postData: '{"revision":"same"}' });

  expect(recovery.recordStart(aborted, owner)).toBeUndefined();
  expect(recovery.recordStart(completed, owner)).toBeUndefined();
  expect(recovery.recordSuccess(completed)).toBeUndefined();
  expect(recovery.recordAbort(aborted)).toBe(false);
});

test.each([
  ["GET", true],
  ["HEAD", true],
  ["POST", false],
] as const)("classifies %s recovery as idempotent: %s", (method, expected) => {
  expect(isIdempotentReadRequest(request({ method }))).toBe(expected);
});

test.each([
  "backfilled stream with successor ready before abort",
  "backfilled stream aborted before successor readiness",
] as const)("proves a workspace stream replacement for a %s", (ordering) => {
  const owner = { id: 1 };
  const replacement = new WorkspaceEventStreamReplacementWindow(
    "http://127.0.0.1:4321/_marimo-studio/dev/events",
  );
  const previous = workspaceEventRequest(1);
  const current = workspaceEventRequest(2);
  expect(replacement.recordStart(previous, owner)).toBe(true);
  replacement.recordResponse(previous, 200);
  expect(replacement.recordStart(current, owner)).toBe(true);

  if (ordering === "backfilled stream with successor ready before abort") {
    replacement.recordResponse(current, 200);
    expect(replacement.recordAbort(previous)).toBe(true);
  } else {
    expect(replacement.recordAbort(previous)).toBe(true);
    replacement.recordResponse(current, 200);
  }

  expect(replacement.readyToRecover()).toBe(true);
  expect(replacement.recover()).toBe(true);
  expect(replacement.diagnostics()).toEqual([]);
});

test("workspace stream replacement rejects an extra reconnect generation", () => {
  const owner = { id: 1 };
  const replacement = new WorkspaceEventStreamReplacementWindow(
    "http://127.0.0.1:4321/_marimo-studio/dev/events",
    1,
  );
  const first = workspaceEventRequest(1);
  const second = workspaceEventRequest(2);
  const third = workspaceEventRequest(3);
  replacement.recordStart(first, owner);
  replacement.recordResponse(first, 200);
  replacement.recordStart(second, owner);
  replacement.recordResponse(second, 200);
  replacement.recordAbort(first);
  replacement.recordStart(third, owner);
  replacement.recordResponse(third, 200);
  replacement.recordAbort(second);

  expect(replacement.recover()).toBe(false);
  expect(replacement.diagnostics()).toContain(
    "expected 1 workspace event stream replacement(s), saw 2",
  );
});

test("workspace stream replacement rejects an extra live survivor", () => {
  const owner = { id: 1 };
  const replacement = new WorkspaceEventStreamReplacementWindow(
    "http://127.0.0.1:4321/_marimo-studio/dev/events",
    1,
  );
  const first = workspaceEventRequest(1);
  const second = workspaceEventRequest(2);
  const duplicate = workspaceEventRequest(3);
  replacement.recordStart(first, owner);
  replacement.recordResponse(first, 200);
  replacement.recordStart(second, owner);
  replacement.recordResponse(second, 200);
  replacement.recordAbort(first);
  replacement.recordStart(duplicate, owner);
  replacement.recordResponse(duplicate, 200);

  expect(replacement.recover()).toBe(false);
  expect(replacement.diagnostics()).toContain(
    "workspace event stream replacement did not retain exactly one ready survivor per owner",
  );
});

test("workspace stream replacement permits an exactly retired owner", () => {
  const firstOwner = { id: 1 };
  const retiredOwner = { id: 2 };
  const replacement = new WorkspaceEventStreamReplacementWindow(
    "http://127.0.0.1:4321/_marimo-studio/dev/events",
    2,
  );
  const firstOld = workspaceEventRequest(1);
  const firstCurrent = workspaceEventRequest(2);
  const retiredOld = workspaceEventRequest(3);
  const retiredCurrent = workspaceEventRequest(4);
  for (const [old, current, owner] of [
    [firstOld, firstCurrent, firstOwner],
    [retiredOld, retiredCurrent, retiredOwner],
  ] as const) {
    replacement.recordStart(old, owner);
    replacement.recordResponse(old, 200);
    replacement.recordStart(current, owner);
    replacement.recordResponse(current, 200);
    replacement.recordAbort(old);
  }

  expect(replacement.retireOwner(retiredOwner)).toBe(true);
  expect(replacement.recover()).toBe(true);
  expect(replacement.diagnostics()).toEqual([]);
});

test("workspace stream replacement stays bound to its exact route and owner", () => {
  const owner = { id: 1 };
  const replacement = new WorkspaceEventStreamReplacementWindow(
    "http://127.0.0.1:4321/_marimo-studio/dev/events",
  );
  const previous = workspaceEventRequest(1);
  const otherRoute = workspaceEventRequest(2, {
    url: "http://127.0.0.1:4321/mounted/_marimo-studio/dev/events?marimo_studio_connection=2",
  });
  const otherOwner = workspaceEventRequest(3);
  replacement.recordStart(previous, owner);
  replacement.recordResponse(previous, 200);
  expect(replacement.recordStart(otherRoute, owner)).toBe(false);
  expect(replacement.recordStart(otherOwner, { id: 2 })).toBe(true);
  replacement.recordResponse(otherOwner, 200);
  expect(replacement.recordAbort(previous)).toBe(true);

  expect(replacement.recover()).toBe(false);
  expect(replacement.diagnostics()).toContain(
    "workspace event stream replacement retained 1 abort(s) without a newer ready generation",
  );
});

test("workspace stream replacement rejects a missing generation", () => {
  const replacement = new WorkspaceEventStreamReplacementWindow(
    "http://127.0.0.1:4321/_marimo-studio/dev/events",
  );
  expect(
    replacement.recordStart(
      workspaceEventRequest(1, {
        url: "http://127.0.0.1:4321/_marimo-studio/dev/events",
      }),
      { id: 1 },
    ),
  ).toBe(true);
  expect(replacement.recover()).toBe(false);
  expect(replacement.diagnostics()).toContain(
    "workspace event stream replacement observed an invalid generation",
  );
});
