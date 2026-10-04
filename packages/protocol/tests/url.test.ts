import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { appendUrlPath } from "../src/url.ts";

test("appended URL paths preserve notebook selectors", () => {
  assert.equal(
    appendUrlPath("https://host/s/f3a9/_marimo-studio/views?file=analysis.py", "dashboard/config"),
    "https://host/s/f3a9/_marimo-studio/views/dashboard/config?file=analysis.py",
  );
});

test("appended URL paths require an absolute source", () => {
  assert.throws(() => appendUrlPath("/_marimo-studio/views", "dashboard/config"), TypeError);
});
