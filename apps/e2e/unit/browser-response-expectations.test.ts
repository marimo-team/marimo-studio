import { expect, test } from "vite-plus/test";

import { BrowserResponseExpectations } from "../tests/browser-response-expectations.ts";

const response = (text: Promise<string>) => ({
  status: () => 409,
  text: () => text,
  url: () => "http://127.0.0.1:4321/_marimo-studio/views/dashboard/config",
});

test("an observed response keeps its reserved allowance while the body is pending", async () => {
  let release!: (body: string) => void;
  const body = new Promise<string>((resolve) => {
    release = resolve;
  });
  const expectations = new BrowserResponseExpectations();
  const recovered = expectations.expect({
    status: 409,
    path: /^\/_marimo-studio\/views\/dashboard\/config$/,
    error: "runtime-sync-pending",
  });

  const inspection = expectations.inspect(response(body));
  recovered();
  release(JSON.stringify({ error: "runtime-sync-pending" }));

  await expect(inspection).resolves.toBeUndefined();
  expect(expectations.diagnostics()).toEqual([]);
});

test("a response first observed after recovery remains diagnostic", async () => {
  const expectations = new BrowserResponseExpectations();
  const recovered = expectations.expect({
    status: 409,
    path: /^\/_marimo-studio\/views\/dashboard\/config$/,
    error: "runtime-sync-pending",
  });
  recovered();

  await expect(
    expectations.inspect(response(Promise.resolve('{"error":"runtime-sync-pending"}'))),
  ).resolves.toContain("http 409 runtime-sync-pending");
  expect(expectations.diagnostics()).toEqual([expect.stringContaining("exactly 1 time(s), saw 0")]);
});

test("concurrent responses claim distinct error allowances on the same route", async () => {
  const expectations = new BrowserResponseExpectations();
  const recoverFirst = expectations.expect({
    status: 409,
    path: /^\/_marimo-studio\/views\/dashboard\/config$/,
    error: "first-error",
  });
  const recoverSecond = expectations.expect({
    status: 409,
    path: /^\/_marimo-studio\/views\/dashboard\/config$/,
    error: "second-error",
  });

  await expect(
    Promise.all([
      expectations.inspect(response(Promise.resolve('{"error":"first-error"}'))),
      expectations.inspect(response(Promise.resolve('{"error":"second-error"}'))),
    ]),
  ).resolves.toEqual([undefined, undefined]);
  recoverFirst();
  recoverSecond();
  expect(expectations.diagnostics()).toEqual([]);
});

test("concurrent responses cannot overclaim one exact error allowance", async () => {
  const expectations = new BrowserResponseExpectations();
  const recovered = expectations.expect({
    status: 409,
    path: /^\/_marimo-studio\/views\/dashboard\/config$/,
    error: "runtime-sync-pending",
  });

  const results = await Promise.all([
    expectations.inspect(response(Promise.resolve('{"error":"runtime-sync-pending"}'))),
    expectations.inspect(response(Promise.resolve('{"error":"runtime-sync-pending"}'))),
  ]);
  expect(results.filter((result) => result === undefined)).toHaveLength(1);
  expect(results.filter((result) => result?.includes("http 409"))).toHaveLength(1);
  recovered();
  expect(expectations.diagnostics()).toEqual([]);
});
