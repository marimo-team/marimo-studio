import assert from "node:assert/strict";
import { beforeEach, test, vi } from "vite-plus/test";

import { DevelopmentEvents } from "../src/document/events.ts";

class EventSourceStub extends EventTarget {
  static instances: EventSourceStub[] = [];
  closed = false;

  constructor(readonly url: string) {
    super();
    EventSourceStub.instances.push(this);
  }

  close(): void {
    this.closed = true;
  }

  emit(type: string, data?: string): void {
    this.dispatchEvent(data === undefined ? new Event(type) : new MessageEvent(type, { data }));
  }
}

beforeEach(() => {
  EventSourceStub.instances = [];
  vi.stubGlobal("EventSource", EventSourceStub);
});

test("closed development streams ignore late events", () => {
  const ready = vi.fn();
  const changed = vi.fn();
  const events = new DevelopmentEvents();
  events.connect("/first", ready, changed);
  const first = EventSourceStub.instances[0];

  events.connect("/second", ready, changed);
  const second = EventSourceStub.instances[1];
  first?.emit("ready");
  first?.emit("change", JSON.stringify({ kind: "html" }));

  assert.equal(first?.closed, true);
  assert.equal(ready.mock.calls.length, 0);
  assert.equal(changed.mock.calls.length, 0);

  second?.emit("ready");
  second?.emit("change", JSON.stringify({ kind: "runtime" }));
  assert.equal(ready.mock.calls.length, 1);
  assert.deepEqual(changed.mock.calls, [["runtime"]]);

  events.close();
  second?.emit("ready");
  assert.equal(second?.closed, true);
  assert.equal(ready.mock.calls.length, 1);
});
