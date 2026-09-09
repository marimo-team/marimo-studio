import { expect, test } from "vite-plus/test";

import {
  ProjectionReadRequestWindow,
  projectionReadRequestKind,
  projectionReadRouteKind,
} from "../tests/projection-read-window.ts";

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

const signedProjectionUrl = (kind: "outputs" | "values") =>
  `http://127.0.0.1:4321/_marimo-studio/presentation/r.capability/_marimo-studio/views/dashboard/${kind}`;

const projectionRequest = (kind: "outputs" | "values", options: RequestOptions = {}) =>
  request({
    ...options,
    method: options.method ?? "POST",
    url: options.url ?? signedProjectionUrl(kind),
  });

const wireProjections = (targets: readonly string[], identity = "stable") =>
  targets.map((target, index) => ({
    instanceId: `${identity}-instance-${index}`,
    siteId: `${identity}-site-${index}`,
    target,
  }));

const valueProjectionRequestAt = (
  targets: readonly string[],
  revision: string,
  identity = "stable",
) => {
  const projections = wireProjections(targets, identity);
  return projectionRequest("values", {
    postData: JSON.stringify({
      activeProjections: projections,
      projections,
      revision,
    }),
  });
};

const valueProjectionRequest = (...targets: string[]) =>
  valueProjectionRequestAt(targets, "revision-a");

const outputProjectionRequest = (
  targets: readonly string[],
  revision: string,
  identity = "stable",
  activeTargets: readonly string[] = targets,
) =>
  projectionRequest("outputs", {
    postData: JSON.stringify({
      activeProjections: wireProjections(activeTargets, identity),
      projections: wireProjections(targets, identity),
      revision,
    }),
  });

const outputProjectionRequestWith = (
  projections: ReturnType<typeof wireProjections>,
  revision: string,
) =>
  projectionRequest("outputs", {
    postData: JSON.stringify({
      activeProjections: [...projections].reverse(),
      projections,
      revision,
    }),
  });
test("recognizes only POST reads on signed projection routes", () => {
  const outputs = projectionRequest("outputs");
  expect(projectionReadRouteKind(outputs.url())).toBe("outputs");
  expect(projectionReadRequestKind(outputs)).toBe("outputs");
  expect(projectionReadRequestKind(projectionRequest("values", { method: "GET" }))).toBeUndefined();
  expect(
    projectionReadRequestKind(
      projectionRequest("values", {
        url: "http://127.0.0.1:4321/_marimo-studio/views/dashboard/values",
      }),
    ),
  ).toBeUndefined();
});

test("recovers an abort followed by a newer same-kind success and revision", () => {
  const owner = { id: 1 };
  const window = new ProjectionReadRequestWindow(owner, "revision-a");
  const old = outputProjectionRequest(["metric"], "revision-a");
  const current = outputProjectionRequest(["metric"], "revision-b");
  expect(window.recordStart(old, owner, 1)).toBe(true);
  expect(window.recordAbort(old)).toBe(true);
  window.seal();
  window.recordStart(current, owner, 2);
  window.recordResponse(current, owner, 2, 200);
  expect(window.recover("revision-b")).toBe(true);
  expect(window.diagnostics()).toEqual([]);
});

test("recovers when the newer success arrives before the captured abort", () => {
  const owner = { id: 1 };
  const window = new ProjectionReadRequestWindow(owner, "revision-a");
  const old = valueProjectionRequestAt(["metric"], "revision-a");
  const current = valueProjectionRequestAt(["metric"], "revision-b");
  window.recordStart(old, owner, 1);
  window.recordStart(current, owner, 2);
  window.seal();
  window.recordResponse(current, owner, 2, 200);
  expect(window.recordAbort(old)).toBe(true);
  expect(window.recover("revision-b")).toBe(true);
  expect(window.diagnostics()).toEqual([]);
});

test("view publication recovers an exact value read at the same wire revision", () => {
  const owner = { id: 1 };
  const window = new ProjectionReadRequestWindow(owner, "projection-a");
  const old = valueProjectionRequestAt(["metric"], "revision-a");
  const current = valueProjectionRequestAt(["metric"], "revision-a");
  window.recordStart(old, owner, 1);
  window.recordAbort(old);
  window.seal();
  const unrelated = valueProjectionRequestAt(["other"], "revision-a");
  window.recordStart(unrelated, owner, 2);
  window.recordResponse(unrelated, owner, 2, 200);
  expect(window.readyToRecover("projection-b")).toBe(false);
  window.recordStart(current, owner, 3);
  window.recordResponse(current, owner, 3, 200);

  expect(window.readyToRecover("projection-a")).toBe(false);
  expect(window.recover("projection-b")).toBe(true);
  expect(window.diagnostics()).toEqual([]);
});

test("an empty values read carries no recovery obligation", () => {
  const owner = { id: 1 };
  const window = new ProjectionReadRequestWindow(owner, "projection-a");
  const empty = valueProjectionRequestAt([], "revision-a");
  expect(window.recordStart(empty, owner, 1)).toBe(true);
  expect(window.recordAbort(empty)).toBe(true);
  window.seal();
  expect(window.recover("projection-b")).toBe(true);
  expect(window.diagnostics()).toEqual([]);
});

test.each([
  ["same wire revision", outputProjectionRequest(["metric"], "revision-a")],
  ["unrelated target", outputProjectionRequest(["other"], "revision-b")],
  ["duplicate target", outputProjectionRequest(["metric", "metric"], "revision-b")],
  ["different tuple", outputProjectionRequest(["metric"], "revision-b", "relocated")],
  ["malformed body", projectionRequest("outputs")],
] as const)("exact successor proof rejects a %s response", (_label, successor) => {
  const owner = { id: 1 };
  const window = new ProjectionReadRequestWindow(owner, "projection-a");
  const old = outputProjectionRequest(["metric"], "revision-a");
  window.recordStart(old, owner, 1);
  window.recordAbort(old);
  window.seal();
  window.recordStart(successor, owner, 2);
  window.recordResponse(successor, owner, 2, 200);
  expect(window.readyToRecover("projection-b")).toBe(false);
});

test("exact output proof permits current active ownership to change", () => {
  const owner = { id: 1 };
  const window = new ProjectionReadRequestWindow(owner, "projection-a");
  const old = outputProjectionRequest(["summary"], "revision-a", "stable", ["summary", "table"]);
  const successor = outputProjectionRequest(["summary"], "revision-b", "stable", [
    "summary",
    "new-output",
  ]);
  window.recordStart(old, owner, 1);
  window.recordAbort(old);
  window.seal();
  window.recordStart(successor, owner, 2);
  window.recordResponse(successor, owner, 2, 200);
  expect(window.readyToRecover("projection-b")).toBe(true);
});

test("exact output proof replaces an ownership sync through the same active projection set", () => {
  const owner = { id: 1 };
  const window = new ProjectionReadRequestWindow(owner, "projection-a");
  const old = outputProjectionRequest([], "revision-a", "stable", ["summary", "table"]);
  const successor = outputProjectionRequest(["summary"], "revision-b", "stable", [
    "summary",
    "table",
  ]);
  window.recordStart(old, owner, 1);
  window.recordAbort(old);
  window.seal();
  window.recordStart(successor, owner, 2);
  window.recordResponse(successor, owner, 2, 200);
  expect(window.readyToRecover("projection-b")).toBe(true);
});

test("exact output ownership sync rejects a relocated active tuple", () => {
  const owner = { id: 1 };
  const window = new ProjectionReadRequestWindow(owner, "projection-a");
  const old = outputProjectionRequest([], "revision-a", "stable", ["summary", "table"]);
  const successor = outputProjectionRequest(["summary"], "revision-b", "relocated", [
    "summary",
    "table",
  ]);
  window.recordStart(old, owner, 1);
  window.recordAbort(old);
  window.seal();
  window.recordStart(successor, owner, 2);
  window.recordResponse(successor, owner, 2, 200);
  expect(window.readyToRecover("projection-b")).toBe(false);
});

test("exact output proof treats projection tuples as an order-independent multiset", () => {
  const owner = { id: 1 };
  const window = new ProjectionReadRequestWindow(owner, "projection-a");
  const projections = wireProjections(["summary", "table"]);
  const old = outputProjectionRequestWith(projections, "revision-a");
  const successor = outputProjectionRequestWith([...projections].reverse(), "revision-b");
  window.recordStart(old, owner, 1);
  window.recordAbort(old);
  window.seal();
  window.recordStart(successor, owner, 2);
  window.recordResponse(successor, owner, 2, 200);
  expect(window.readyToRecover("projection-b")).toBe(true);
});

test("view transition proof permits exact target relocation", () => {
  const owner = { id: 1 };
  const window = new ProjectionReadRequestWindow(owner, "projection-a", 512, "view-transition");
  const old = valueProjectionRequestAt(["metric"], "revision-a", "dashboard");
  const successor = valueProjectionRequestAt(["metric"], "revision-b", "report");
  window.recordStart(old, owner, 1);
  window.recordAbort(old);
  window.seal();
  window.recordStart(successor, owner, 2);
  window.recordResponse(successor, owner, 2, 200);
  expect(window.readyToRecover("projection-b")).toBe(true);
});

test("view transition output cleanup proves retired ownership", () => {
  const owner = { id: 1 };
  const window = new ProjectionReadRequestWindow(owner, "projection-a", 512, "view-transition");
  const old = outputProjectionRequest(["summary"], "revision-a", "dashboard");
  const successor = outputProjectionRequest([], "revision-b", "report", ["report-output"]);
  window.recordStart(old, owner, 1);
  window.recordAbort(old);
  window.seal();
  window.recordStart(successor, owner, 2);
  window.recordResponse(successor, owner, 2, 200);
  expect(window.readyToRecover("projection-b")).toBe(true);
});

test("view transition output cleanup keeps active aborted targets fail-closed", () => {
  const owner = { id: 1 };
  const window = new ProjectionReadRequestWindow(owner, "projection-a", 512, "view-transition");
  const old = outputProjectionRequest(["summary"], "revision-a", "dashboard");
  const successor = outputProjectionRequest([], "revision-b", "report", ["summary"]);
  window.recordStart(old, owner, 1);
  window.recordAbort(old);
  window.seal();
  window.recordStart(successor, owner, 2);
  window.recordResponse(successor, owner, 2, 200);
  expect(window.readyToRecover("projection-b")).toBe(false);
});

test("view transition proof rejects mixed or same-revision successors", () => {
  const owner = { id: 1 };
  const old = valueProjectionRequestAt(["metric"], "revision-a", "dashboard");
  for (const successor of [
    valueProjectionRequestAt(["metric", "other"], "revision-b", "report"),
    valueProjectionRequestAt(["metric"], "revision-a", "report"),
  ]) {
    const window = new ProjectionReadRequestWindow(owner, "projection-a", 512, "view-transition");
    window.recordStart(old, owner, 1);
    window.recordAbort(old);
    window.seal();
    window.recordStart(successor, owner, 2);
    window.recordResponse(successor, owner, 2, 200);
    expect(window.readyToRecover("projection-b")).toBe(false);
  }
});

test("keeps owner, route, method, and read kind exact", () => {
  const owner = { id: 1 };
  const otherOwner = { id: 2 };
  const window = new ProjectionReadRequestWindow(owner, "revision-a");
  expect(window.recordStart(projectionRequest("outputs"), otherOwner, 1)).toBe(false);
  expect(window.recordStart(projectionRequest("outputs", { method: "GET" }), owner, 2)).toBe(false);
  expect(window.recordStart(request({ method: "POST" }), owner, 3)).toBe(false);
  const old = outputProjectionRequest(["metric"], "revision-a");
  const wrongKind = valueProjectionRequestAt(["metric"], "revision-b");
  window.recordStart(old, owner, 4);
  expect(window.recordAbort(old)).toBe(true);
  window.seal();
  window.recordStart(wrongKind, owner, 5);
  window.recordResponse(wrongKind, owner, 5, 200);
  expect(window.recover("revision-b")).toBe(false);
});

test("non-abort terminals remain visible and do not need recovery", () => {
  const owner = { id: 1 };
  const window = new ProjectionReadRequestWindow(owner, "revision-a");
  const failed = projectionRequest("outputs");
  window.recordStart(failed, owner, 1);
  window.recordFailure(failed);
  expect(window.recordAbort(failed)).toBe(false);
  window.seal();
  expect(window.diagnostics()).toEqual([]);
});

test("terminal missing values recover while outputs still require a newer success", () => {
  const owner = { id: 1 };
  const window = new ProjectionReadRequestWindow(owner, "revision-a");
  const oldOutput = outputProjectionRequest(["summary"], "revision-a");
  const oldValue = valueProjectionRequest("missing");
  const currentOutput = outputProjectionRequest(["summary"], "revision-b");
  window.recordStart(oldOutput, owner, 1);
  window.recordStart(oldValue, owner, 2);
  expect(window.recordAbort(oldOutput)).toBe(true);
  expect(window.recordAbort(oldValue)).toBe(true);
  expect(window.terminalizeValues(["missing"])).toBe(true);
  window.seal();
  window.recordStart(currentOutput, owner, 3);
  window.recordResponse(currentOutput, owner, 3, 200);
  expect(window.recover("revision-b")).toBe(true);
  expect(window.diagnostics()).toEqual([]);
});

test("terminal missing values include a late exact candidate abort", () => {
  const owner = { id: 1 };
  const window = new ProjectionReadRequestWindow(owner, "revision-a");
  const oldValue = valueProjectionRequest("missing");
  window.recordStart(oldValue, owner, 1);
  expect(window.terminalizeValues(["missing"])).toBe(true);
  expect(window.recordAbort(oldValue)).toBe(true);
  window.seal();
  expect(window.recover("revision-b")).toBe(true);
  expect(window.diagnostics()).toEqual([]);
});

test("terminal missing values do not relax output replacement proof", () => {
  const owner = { id: 1 };
  const window = new ProjectionReadRequestWindow(owner, "revision-a");
  const oldOutput = outputProjectionRequest(["summary"], "revision-a");
  const oldValue = valueProjectionRequest("missing");
  window.recordStart(oldOutput, owner, 1);
  window.recordStart(oldValue, owner, 2);
  window.recordAbort(oldOutput);
  window.recordAbort(oldValue);
  window.terminalizeValues(["missing"]);
  window.seal();
  expect(window.recover("revision-b")).toBe(false);
});

test.each([
  ["unrelated", ["live"]],
  ["mixed", ["missing", "live"]],
] as const)("terminal missing values keep a %s request fail-closed", (_label, targets) => {
  const owner = { id: 1 };
  const window = new ProjectionReadRequestWindow(owner, "revision-a");
  const oldValue = valueProjectionRequest(...targets);
  window.recordStart(oldValue, owner, 1);
  window.recordAbort(oldValue);
  window.terminalizeValues(["missing"]);
  window.seal();
  expect(window.recover("revision-b")).toBe(false);
});

test("a values request started after terminalization remains visible", () => {
  const owner = { id: 1 };
  const window = new ProjectionReadRequestWindow(owner, "revision-a");
  expect(window.terminalizeValues(["missing"])).toBe(true);
  const late = valueProjectionRequest("missing");
  expect(window.recordStart(late, owner, 1)).toBe(false);
  expect(window.recordAbort(late)).toBe(false);
});

test("values can be terminalized only while the mutation window accepts reads", () => {
  const window = new ProjectionReadRequestWindow({ id: 1 }, "revision-a");
  window.seal();
  expect(window.terminalizeValues(["missing"])).toBe(false);
});

test("active captured requests block recovery", () => {
  const owner = { id: 1 };
  const window = new ProjectionReadRequestWindow(owner, "revision-a");
  window.recordStart(projectionRequest("outputs"), owner, 1);
  window.seal();
  expect(window.readyToRecover("revision-b")).toBe(false);
  expect(window.recover("revision-b")).toBe(false);
});

test("rejects recovery when the projection revision is unchanged", () => {
  const owner = { id: 1 };
  const window = new ProjectionReadRequestWindow(owner, "revision-a");
  window.seal();
  expect(window.recover("revision-a")).toBe(false);
});

test("recovery readiness waits for the exact newer response without poisoning state", () => {
  const owner = { id: 1 };
  const window = new ProjectionReadRequestWindow(owner, "revision-a");
  const old = outputProjectionRequest(["metric"], "revision-a");
  const successor = outputProjectionRequest(["metric"], "revision-b");
  window.recordStart(old, owner, 1);
  window.recordAbort(old);
  window.seal();
  window.recordStart(successor, owner, 2);
  expect(window.readyToRecover("revision-b")).toBe(false);
  expect(window.recover("revision-b")).toBe(false);
  window.recordResponse(successor, owner, 2, 200);
  expect(window.readyToRecover("revision-b")).toBe(true);
  expect(window.recover("revision-b")).toBe(true);
  expect(window.diagnostics()).toEqual([]);
});

test("the same start cannot prove a newer abort", () => {
  const owner = { id: 1 };
  const window = new ProjectionReadRequestWindow(owner, "revision-a");
  const old = outputProjectionRequest(["metric"], "revision-a");
  const success = outputProjectionRequest(["metric"], "revision-b");
  window.recordStart(old, owner, 2);
  window.recordAbort(old);
  window.seal();
  window.recordStart(success, owner, 2);
  window.recordResponse(success, owner, 2, 200);
  expect(window.recover("revision-b")).toBe(false);
});

test("a non-success status cannot prove a captured abort", () => {
  const owner = { id: 1 };
  const window = new ProjectionReadRequestWindow(owner, "revision-a");
  const old = valueProjectionRequestAt(["metric"], "revision-a");
  const response = valueProjectionRequestAt(["metric"], "revision-b");
  window.recordStart(old, owner, 1);
  window.recordAbort(old);
  window.seal();
  window.recordStart(response, owner, 2);
  window.recordResponse(response, owner, 2, 409);
  expect(window.recover("revision-b")).toBe(false);
});

test("recovery before seal fails closed", () => {
  const window = new ProjectionReadRequestWindow({ id: 1 }, "revision-a");
  expect(window.recover("revision-b")).toBe(false);
});

test("bounds captured projection requests and fails closed on overflow", () => {
  const owner = { id: 1 };
  const window = new ProjectionReadRequestWindow(owner, "revision-a", 1);
  expect(window.recordStart(projectionRequest("outputs"), owner, 1)).toBe(true);
  expect(window.recordStart(projectionRequest("values"), owner, 2)).toBe(false);
});
