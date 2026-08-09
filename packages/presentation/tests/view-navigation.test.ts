import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { viewNavigationForUrl } from "../src/document/view-navigation.ts";

const selection = (href: string, currentView = "novice") =>
  viewNavigationForUrl({
    href,
    origin: "https://example.test",
    publicRootUrl: "/proxy/token/",
    documentRootUrl: "/proxy/token/",
    publicQuery: "",
    views: ["novice", "intermediate", "expert"],
    currentView,
  });

const authoredRoot =
  "https://example.test/proxy/token/_marimo-studio/notebooks/YW5hbHlzaXMucHk/views/";
const authoredSelection = (path: string) =>
  viewNavigationForUrl({
    href: `${authoredRoot}${path}`,
    origin: "https://example.test",
    publicRootUrl: "/proxy/token/?file=analysis.py",
    documentRootUrl: new URL(authoredRoot).pathname,
    publicQuery: "?region=eu",
    views: ["novice", "expert"],
    currentView: "novice",
  });

test("configured view URLs resolve beneath Marimo's base path and identify the current view", () => {
  const base = new URL("/proxy/token/", "https://example.test");

  assert.deepEqual(selection(new URL("./intermediate/", base).href), {
    view: "intermediate",
    current: false,
    documentUrl: "https://example.test/proxy/token/intermediate/",
  });
  assert.deepEqual(selection("https://example.test/proxy/token/expert/"), {
    view: "expert",
    current: false,
    documentUrl: "https://example.test/proxy/token/expert/",
  });
  assert.deepEqual(selection("https://example.test/proxy/token/novice/"), {
    view: "novice",
    current: true,
    documentUrl: "https://example.test/proxy/token/novice/",
  });
});

test("authored routes navigate through their public notebook URL", () => {
  const cases = [
    [
      "expert/",
      {
        view: "expert",
        current: false,
        documentUrl: "https://example.test/proxy/token/expert/?file=analysis.py&region=eu",
      },
    ],
    [
      "novice/#details",
      {
        view: "novice",
        current: true,
        documentUrl: "https://example.test/proxy/token/novice/?file=analysis.py&region=eu#details",
      },
    ],
    [
      "novice/?region=us",
      {
        view: "novice",
        current: true,
        documentUrl: "https://example.test/proxy/token/novice/?file=analysis.py&region=us",
      },
    ],
  ] as const;

  for (const [path, expected] of cases) {
    assert.deepEqual(authoredSelection(path), expected);
  }
});

test("view navigation leaves other links to the browser", () => {
  assert.deepEqual(selection("https://other.test/proxy/token/intermediate/"), undefined);
  assert.deepEqual(selection("https://example.test/intermediate/"), undefined);
  assert.deepEqual(selection("https://example.test/proxy/intermediate/"), undefined);
  assert.deepEqual(selection("https://example.test/proxy/token/intermediate/?region=eu"), {
    view: "intermediate",
    current: false,
    documentUrl: "https://example.test/proxy/token/intermediate/?region=eu",
  });
  assert.deepEqual(selection("https://example.test/proxy/token/intermediate/#results"), {
    view: "intermediate",
    current: false,
    documentUrl: "https://example.test/proxy/token/intermediate/#results",
  });
  assert.deepEqual(selection("https://example.test/proxy/token/missing/"), undefined);
});
