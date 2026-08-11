import { QUERY_OPERATION_QUERY_PARAM } from "@marimo-studio/protocol/query";
import { expect, it, vi } from "vite-plus/test";

import { observeFrameQuery } from "../src/features/preview/query-sync.ts";

const queryFrame = () => {
  const child = new EventTarget() as EventTarget & {
    history: History;
    location: { href: string; search: string };
  };
  child.location = { href: "http://localhost/notebook", search: "" };
  const navigate = (_data: unknown, _unused: string, url?: string | URL | null) => {
    if (url !== undefined && url !== null) {
      const next = new URL(String(url), child.location.href);
      child.location.href = next.href;
      child.location.search = next.search;
    }
  };
  child.history = {
    pushState: navigate,
    replaceState: navigate,
  } as History;
  const frame = new EventTarget() as HTMLIFrameElement;
  Object.defineProperty(frame, "contentWindow", { value: child });
  return { child, frame };
};

it("labels a kernel query echo with its causal operation", () => {
  const { child, frame } = queryFrame();
  const receive = vi.fn();
  const stop = observeFrameQuery(frame, receive);
  frame.dispatchEvent(new Event("load"));

  child.history.replaceState({}, "", `?${QUERY_OPERATION_QUERY_PARAM}=query_1`);
  child.history.replaceState({}, "", `?${QUERY_OPERATION_QUERY_PARAM}=query_1&region=preview`);
  child.history.replaceState({}, "", "?region=preview");

  expect(receive.mock.calls).toEqual([
    ["", undefined, false],
    ["", "query_1", false],
    ["?region=preview", "query_1", false],
    ["?region=preview", "query_1", true],
  ]);
  stop();
});

it("moves query observations to a replacement subscriber", () => {
  const { child, frame } = queryFrame();
  const first = vi.fn();
  const second = vi.fn();
  const stopFirst = observeFrameQuery(frame, first);
  frame.dispatchEvent(new Event("load"));
  stopFirst();

  const stopSecond = observeFrameQuery(frame, second);
  frame.dispatchEvent(new Event("load"));
  child.history.replaceState({}, "", "?region=editor");

  expect(first).toHaveBeenCalledTimes(1);
  expect(second.mock.calls).toEqual([
    ["", undefined, false],
    ["?region=editor", undefined, false],
  ]);
  stopSecond();
});
