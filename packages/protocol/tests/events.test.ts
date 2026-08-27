import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import {
  parseActivationAckResponse,
  parseActiveViewRequest,
  parseEditorDocumentMutation,
  parseEditorSessionBinding,
  parseObserveViewRequest,
  parsePresentationBuild,
  parsePresentationChange,
  parseWorkspaceChange,
} from "../src/development-events.ts";
import { parseSourceChanges } from "../src/source-events.ts";

test("development events accept authoritative workspace changes", () => {
  assert.deepEqual(parseWorkspaceChange('{"kind":"project"}'), "project");
  assert.deepEqual(parseWorkspaceChange('{"kind":"build"}'), "build");
  assert.deepEqual(parseWorkspaceChange('{"kind":"presentation"}'), "presentation");
  assert.deepEqual(parseWorkspaceChange('{"kind":"views"}'), "views");
  assert.deepEqual(parseWorkspaceChange('{"kind":"html"}'), undefined);
  assert.deepEqual(parseWorkspaceChange("invalid"), undefined);
});

test("presentation build events identify admission boundaries", () => {
  assert.deepEqual(parsePresentationBuild('{"kind":"build","phase":"building","files":[]}'), {
    phase: "building",
  });
  assert.deepEqual(
    parsePresentationBuild(
      '{"kind":"build","build":{"phase":"ready"},"revision":"revision-2","files":[]}',
    ),
    { phase: "complete", revision: "revision-2" },
  );
  assert.deepEqual(
    parsePresentationBuild(
      '{"kind":"build","build":{"phase":"failed"},"revision":null,"files":[]}',
    ),
    { phase: "complete", revision: null },
  );
  assert.equal(parsePresentationBuild('{"kind":"project"}'), undefined);
});

test("presentation changes carry the published revision", () => {
  assert.deepEqual(
    parsePresentationChange(
      '{"kind":"presentation","view":"dashboard","revision":"revision-2","files":[]}',
    ),
    { view: "dashboard", revision: "revision-2" },
  );
  assert.equal(parsePresentationChange('{"kind":"presentation"}'), undefined);
});

test("development events decode active-view requests", () => {
  assert.deepEqual(parseActiveViewRequest('{"schema":1,"generation":4,"view":"report"}'), {
    schema: 1,
    generation: 4,
    view: "report",
  });
  assert.deepEqual(parseActiveViewRequest('{"schema":1,"view":""}'), undefined);
});

test("activation acknowledgements expose terminal browser outcomes", () => {
  for (const outcome of ["applied", "retryable", "rejected"] as const) {
    assert.deepEqual(parseActivationAckResponse({ schema: 1, outcome }), {
      schema: 1,
      outcome,
    });
  }
  assert.deepEqual(parseActivationAckResponse({ schema: 1, outcome: "unknown" }), undefined);
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

test("editor document mutations require the exact bounded schema", () => {
  const mutation = {
    schema: 1,
    type: "marimo-studio:editor-document-mutation",
    generation: 3,
  } as const;
  assert.deepEqual(parseEditorDocumentMutation(mutation), mutation);
  assert.deepEqual(
    parseEditorDocumentMutation({
      schema: 1,
      type: "marimo-studio:editor-document-saved",
      generation: 3,
    }),
    {
      schema: 1,
      type: "marimo-studio:editor-document-saved",
      generation: 3,
    },
  );
  const applied = {
    schema: 1,
    type: "marimo-studio:editor-document-transaction-applied",
    generation: 3,
    changed: false,
  } as const;
  assert.deepEqual(parseEditorDocumentMutation(applied), applied);
  assert.equal(parseEditorDocumentMutation({ ...applied, changed: "false" }), undefined);
  assert.equal(
    parseEditorDocumentMutation({
      schema: 1,
      type: "marimo-studio:editor-document-transaction-applied",
      generation: 3,
    }),
    undefined,
  );
  assert.equal(parseEditorDocumentMutation({ ...mutation, generation: 0 }), undefined);
  assert.equal(parseEditorDocumentMutation({ ...mutation, extra: true }), undefined);
  assert.equal(parseEditorDocumentMutation({ ...mutation, type: "unknown" }), undefined);
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

test("source events retain valid provider-discovered files", () => {
  assert.deepEqual(
    parseSourceChanges(
      JSON.stringify({
        files: [
          { path: "index.html", revision: "html-r2" },
          { path: "app.css", revision: null },
          { path: "src/App.tsx", revision: "tsx-r2" },
          { path: "../outside.ts", revision: "ignored" },
          { path: "index.html", revision: 42 },
        ],
      }),
    ),
    [
      { path: "index.html", revision: "html-r2" },
      { path: "app.css", revision: null },
      { path: "src/App.tsx", revision: "tsx-r2" },
    ],
  );
  assert.deepEqual(parseSourceChanges("invalid"), []);
});
