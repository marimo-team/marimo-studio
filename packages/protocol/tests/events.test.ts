import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import {
  parseActiveViewRequest,
  parseEditorSessionBinding,
  parseObserveViewRequest,
  parseShellChange,
} from "../src/development-events.ts";
import { parseSourceChanges } from "../src/source-events.ts";

test("development events accept supported shell changes", () => {
  assert.deepEqual(parseShellChange('{"kind":"runtime"}'), "runtime");
  assert.deepEqual(parseShellChange('{"kind":"unknown"}'), undefined);
  assert.deepEqual(parseShellChange("invalid"), undefined);
});

test("development events decode active-view requests", () => {
  assert.deepEqual(parseActiveViewRequest('{"schema":1,"generation":4,"view":"report"}'), {
    schema: 1,
    generation: 4,
    view: "report",
  });
  assert.deepEqual(parseActiveViewRequest('{"schema":1,"view":""}'), undefined);
});

test("development events decode editor session bindings", () => {
  assert.deepEqual(
    parseEditorSessionBinding(
      '{"schema":1,"generation":2,"sessionId":"s_reconnected","replaced":true}',
    ),
    { schema: 1, generation: 2, sessionId: "s_reconnected", replaced: true },
  );
  assert.deepEqual(
    parseEditorSessionBinding(
      '{"schema":1,"generation":0,"sessionId":"s_reconnected","replaced":false}',
    ),
    undefined,
  );
});

test("development events decode browser observation requests", () => {
  const payload = {
    schema: 1,
    requestId: "request-dashboard",
    view: "dashboard",
    runtime: "server",
    runtimeInstance: "runtime-instance",
    revision: "revision-1",
  };
  assert.deepEqual(parseObserveViewRequest(JSON.stringify(payload)), payload);
  assert.deepEqual(
    parseObserveViewRequest(JSON.stringify({ ...payload, activeViewGeneration: 3 })),
    { ...payload, activeViewGeneration: 3 },
  );
  assert.deepEqual(
    parseObserveViewRequest(JSON.stringify({ ...payload, runtimeInstance: "" })),
    undefined,
  );
  assert.deepEqual(
    parseObserveViewRequest(JSON.stringify({ ...payload, activeViewGeneration: -1 })),
    undefined,
  );
});

test("source events retain valid authored files", () => {
  assert.deepEqual(
    parseSourceChanges(
      JSON.stringify({
        files: [
          { path: "index.html", revision: "html-r2" },
          { path: "app.css", revision: null },
          { path: "notes.txt", revision: "ignored" },
          { path: "index.html", revision: 42 },
        ],
      }),
    ),
    [
      { path: "index.html", revision: "html-r2" },
      { path: "app.css", revision: null },
    ],
  );
  assert.deepEqual(parseSourceChanges("invalid"), []);
});
