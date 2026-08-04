import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { viewNavigationForUrl } from "../src/document/view-navigation.ts";

const selection = (href: string, currentView = "novice") =>
  viewNavigationForUrl({
    href,
    origin: "https://example.test",
    rootUrl: "/proxy/token/",
    views: ["novice", "intermediate", "expert"],
    currentView,
  });

test("configured view URLs resolve beneath Marimo's base path", () => {
  const base = new URL("/proxy/token/", "https://example.test");

  assert.deepEqual(selection(new URL("./intermediate/", base).href), {
    view: "intermediate",
    current: false,
  });
  assert.deepEqual(selection("https://example.test/proxy/token/expert/"), {
    view: "expert",
    current: false,
  });
});

test("the active configured view resolves as a navigation no-op", () => {
  assert.deepEqual(selection("https://example.test/proxy/token/novice/"), {
    view: "novice",
    current: true,
  });
});

test("view navigation leaves other links to the browser", () => {
  assert.deepEqual(selection("https://other.test/proxy/token/intermediate/"), undefined);
  assert.deepEqual(selection("https://example.test/intermediate/"), undefined);
  assert.deepEqual(selection("https://example.test/proxy/intermediate/"), undefined);
  assert.deepEqual(
    selection("https://example.test/proxy/token/intermediate/?region=eu"),
    undefined,
  );
  assert.deepEqual(selection("https://example.test/proxy/token/intermediate/#results"), undefined);
  assert.deepEqual(selection("https://example.test/proxy/token/missing/"), undefined);
});
