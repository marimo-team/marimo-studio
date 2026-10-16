import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { parseWorkspaceChange } from "../src/development-events.ts";
import { eventSocketUrl, parseStudioEvent } from "../src/event-socket.ts";

test("event frames carry the event name and its decoded payload", () => {
  const change = parseStudioEvent('{"event":"change","data":{"kind":"views"}}');
  assert.equal(change?.event, "change");
  assert.equal(change && parseWorkspaceChange(change.data), "views");
  assert.equal(parseStudioEvent('{"event":"heartbeat","data":{}}')?.event, "heartbeat");
  assert.equal(parseStudioEvent('{"data":{}}'), undefined);
  assert.equal(parseStudioEvent("event: ready\ndata: {}"), undefined);
});

test("event sockets address the HTTP event route with the matching WebSocket scheme", () => {
  assert.equal(
    eventSocketUrl("http://localhost:2718/_marimo-studio/dev/events?marimo_studio_connection=3"),
    "ws://localhost:2718/_marimo-studio/dev/events?marimo_studio_connection=3",
  );
  assert.equal(
    eventSocketUrl("/base/_marimo-studio/views/report/dev/events", "https://notebooks.example/x/"),
    "wss://notebooks.example/base/_marimo-studio/views/report/dev/events",
  );
});
