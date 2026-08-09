import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { appendUrlPath } from "../src/url.ts";

test("appended URL paths preserve notebook selectors", () => {
  assert.equal(
    appendUrlPath("/_marimo-studio/views?file=analysis.py", "dashboard/config", "https://host/"),
    "https://host/_marimo-studio/views/dashboard/config?file=analysis.py",
  );
});
