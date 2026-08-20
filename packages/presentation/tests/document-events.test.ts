import { afterEach, expect, it, vi } from "vite-plus/test";

import { DevelopmentEvents } from "../src/document/events.ts";

class EventSourceStub {
  static readonly instances: EventSourceStub[] = [];
  private readonly listeners = new Map<string, EventListener>();
  closed = false;

  constructor(readonly url: string) {
    EventSourceStub.instances.push(this);
  }

  addEventListener(type: string, listener: EventListener): void {
    this.listeners.set(type, listener);
  }

  emit(type: string, data?: string): void {
    this.listeners.get(type)?.(
      data === undefined ? new Event(type) : new MessageEvent(type, { data }),
    );
  }

  close(): void {
    this.closed = true;
  }
}

afterEach(() => {
  EventSourceStub.instances.length = 0;
  vi.unstubAllGlobals();
});

it("ignores queued source events after switching view streams", () => {
  vi.stubGlobal("EventSource", EventSourceStub);
  const events = new DevelopmentEvents();
  const ready = vi.fn();
  const changed = vi.fn();

  events.connect("/dashboard/events", ready, changed);
  const dashboard = EventSourceStub.instances[0];
  events.connect("/report/events", ready, changed);
  const report = EventSourceStub.instances[1];

  dashboard?.emit("ready");
  dashboard?.emit("change", JSON.stringify({ schema: 1, kind: "html", files: [] }));
  report?.emit("ready");
  report?.emit("change", JSON.stringify({ schema: 1, kind: "css", files: [] }));

  expect(dashboard?.closed).toBe(true);
  expect(ready).toHaveBeenCalledOnce();
  expect(changed).toHaveBeenCalledOnce();
  expect(changed).toHaveBeenCalledWith("css");
  events.close();
});
