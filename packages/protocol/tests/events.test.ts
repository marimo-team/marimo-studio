import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
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
import { parsePresentationBaseline, parseSourceChanges } from "../src/source-events.ts";

type DevelopmentEventsFixture = {
  sourceChanges: Array<{
    schema: 1;
    kind: "project" | "views";
    files: Array<{ path: string; revision: string | null }>;
  }>;
  presentationBaselines: Array<{
    schema: 1;
    view: string;
    revision: string | null;
  }>;
  presentationBuilds: Array<
    | { schema: 1; kind: "build"; view: string; phase: "building"; files: [] }
    | {
        schema: 1;
        kind: "build";
        view: string;
        build: {
          schema: 1;
          profile: "development";
          phase: "ready" | "failed";
        };
        revision: string | null;
        files: [];
      }
  >;
  presentationChanges: Array<{
    schema: 1;
    kind: "presentation";
    view: string;
    revision: string;
    artifact_revision: string;
    files: [];
  }>;
  activationAcknowledgements: Array<{
    schema: 1;
    outcome: "applied" | "retryable" | "rejected";
  }>;
  activeViewRequests: Array<{ schema: 1; generation: number; view: string }>;
  editorSessionBindings: Array<{
    schema: 1;
    generation: number;
    sessionId: string;
    replaced: boolean;
  }>;
  observationRequests: Array<{
    schema: 1;
    requestId: string;
    view: string;
    runtime: "server" | "wasm";
    runtimeInstance: string;
    revision: string;
    activeViewGeneration?: number;
  }>;
};

// SAFETY: The Python producer test owns this repository fixture, and each
// payload below is passed through its browser parser before use.
const fixture = JSON.parse(
  readFileSync(new URL("../fixtures/development-events.json", import.meta.url), "utf8"),
) as DevelopmentEventsFixture;

test("development event parsers accept the Python producer fixture", () => {
  for (const payload of fixture.sourceChanges) {
    const source = JSON.stringify(payload);
    assert.deepEqual(parseSourceChanges(source), payload.files);
    assert.equal(parseWorkspaceChange(source), payload.kind);
  }
  for (const payload of fixture.presentationBaselines) {
    assert.deepEqual(parsePresentationBaseline(JSON.stringify(payload)), payload);
  }
  for (const payload of fixture.presentationBuilds) {
    const expected =
      "phase" in payload
        ? { phase: "building" }
        : { phase: "complete", revision: payload.revision };
    const source = JSON.stringify(payload);
    assert.deepEqual(parsePresentationBuild(source), expected);
    assert.equal(parseWorkspaceChange(source), payload.kind);
  }
  for (const payload of fixture.presentationChanges) {
    const source = JSON.stringify(payload);
    assert.deepEqual(parsePresentationChange(source), {
      view: payload.view,
      revision: payload.revision,
    });
    assert.equal(parseWorkspaceChange(source), payload.kind);
  }
  for (const payload of fixture.activeViewRequests) {
    assert.deepEqual(parseActiveViewRequest(JSON.stringify(payload)), payload);
  }
  for (const payload of fixture.activationAcknowledgements) {
    assert.deepEqual(parseActivationAckResponse(payload), payload);
  }
  for (const payload of fixture.editorSessionBindings) {
    assert.deepEqual(parseEditorSessionBinding(JSON.stringify(payload)), payload);
  }
  for (const payload of fixture.observationRequests) {
    assert.deepEqual(parseObserveViewRequest(JSON.stringify(payload)), payload);
  }
});

test("development event parsers reject malformed browser contracts", () => {
  assert.equal(parseWorkspaceChange('{"kind":"html"}'), undefined);
  assert.equal(parseWorkspaceChange("invalid"), undefined);
  assert.equal(parsePresentationBuild('{"kind":"project"}'), undefined);
  assert.equal(parsePresentationChange('{"kind":"presentation"}'), undefined);
  assert.equal(parsePresentationBaseline('{"schema":1,"view":"dashboard"}'), undefined);
  assert.equal(parseActiveViewRequest('{"schema":1,"view":""}'), undefined);
  assert.equal(parseActivationAckResponse({ schema: 1, outcome: "unknown" }), undefined);
  assert.equal(
    parseEditorSessionBinding(
      '{"schema":1,"generation":0,"sessionId":"s_reconnected","replaced":false}',
    ),
    undefined,
  );

  const observation = fixture.observationRequests[0];
  assert.ok(observation);
  assert.equal(
    parseObserveViewRequest(JSON.stringify({ ...observation, runtimeInstance: "" })),
    undefined,
  );
  assert.equal(
    parseObserveViewRequest(JSON.stringify({ ...observation, activeViewGeneration: -1 })),
    undefined,
  );
  assert.deepEqual(
    parseSourceChanges(
      JSON.stringify({
        files: [
          { path: "../outside.ts", revision: "ignored" },
          { path: "index.html", revision: 42 },
        ],
      }),
    ),
    [],
  );
  const retained = fixture.sourceChanges[0]?.files[0];
  assert.ok(retained);
  assert.deepEqual(
    parseSourceChanges(
      JSON.stringify({
        files: [retained, { path: "../outside.ts", revision: "ignored" }],
      }),
    ),
    [retained],
  );
  assert.deepEqual(parseSourceChanges("invalid"), []);
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
