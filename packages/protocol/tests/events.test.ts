import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { parseShellChange } from "../src/development-events.ts";
import { parseSourceChanges } from "../src/source-events.ts";

test("development events accept supported shell changes", () => {
  assert.deepEqual(parseShellChange('{"kind":"runtime"}'), "runtime");
  assert.deepEqual(parseShellChange('{"kind":"unknown"}'), undefined);
  assert.deepEqual(parseShellChange("invalid"), undefined);
});

test("source events retain valid authored files", () => {
  assert.deepEqual(
    parseSourceChanges(
      JSON.stringify({
        files: [
          { path: "index.html", revision: "html-r2" },
          { path: "theme.css", revision: "theme-r2" },
          { path: "app.css", revision: null },
          { path: "notes.txt", revision: "ignored" },
          { path: "index.html", revision: 42 },
        ],
      }),
    ),
    [
      { path: "index.html", revision: "html-r2" },
      { path: "theme.css", revision: "theme-r2" },
      { path: "app.css", revision: null },
    ],
  );
  assert.deepEqual(parseSourceChanges("invalid"), []);
});
