import { QUERY_OPERATION_QUERY_PARAM } from "@marimo-studio/protocol/query";
import { expect, it, vi } from "vite-plus/test";

import { observeFrameQuery } from "../src/features/preview/query-sync.ts";

interface HistoryState {
  readonly operation?: string;
}

type QueryLocation = {
  href: string;
  search: string;
};

class QueryHistory {
  constructor(private readonly location: QueryLocation) {}

  pushState(data: HistoryState, unused: string, url?: string | URL | null): void {
    this.navigate(data, unused, url);
  }

  replaceState(data: HistoryState, unused: string, url?: string | URL | null): void {
    this.navigate(data, unused, url);
  }

  private navigate(_data: HistoryState, _unused: string, url?: string | URL | null): void {
    if (url !== undefined && url !== null) {
      const next = new URL(String(url), this.location.href);
      this.location.href = next.href;
      this.location.search = next.search;
    }
  }
}

class QueryWindow extends EventTarget {
  location: QueryLocation;
  history: QueryHistory;

  constructor(href = "http://localhost/notebook") {
    super();
    this.location = this.queryLocation(href);
    this.history = new QueryHistory(this.location);
  }

  navigate(href: string): void {
    this.location = this.queryLocation(href);
    this.history = new QueryHistory(this.location);
  }

  private queryLocation(href: string): QueryLocation {
    const location = new URL(href);
    return { href: location.href, search: location.search };
  }
}

const queryFrame = () => {
  const child = new QueryWindow();
  let childDocument = document.implementation.createHTMLDocument();
  const frame = document.createElement("iframe");
  Object.defineProperties(frame, {
    contentDocument: { get: () => childDocument },
    contentWindow: { value: child },
  });
  return {
    child,
    frame,
    navigate(href: string) {
      child.navigate(href);
      childDocument = document.implementation.createHTMLDocument();
      frame.dispatchEvent(new Event("load"));
    },
  };
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

it("reinstalls query observation after iframe navigation keeps its window proxy", () => {
  const { child, frame, navigate } = queryFrame();
  const receive = vi.fn();
  const stop = observeFrameQuery(frame, receive);
  frame.dispatchEvent(new Event("load"));
  child.history.replaceState({}, "", "?region=before");

  navigate("http://localhost/notebook?region=loaded");
  child.history.replaceState({}, "", "?region=after");

  expect(receive.mock.calls).toEqual([
    ["", undefined, false],
    ["?region=before", undefined, false],
    ["?region=loaded", undefined, false],
    ["?region=after", undefined, false],
  ]);
  stop();
});
