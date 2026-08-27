import { expect, test, vi } from "vite-plus/test";

import { ReceiverRefreshHandshake } from "../src/document/receiver-refresh.ts";

test("a receiver refresh emits one ordered handshake across superseded work", () => {
  const events: string[] = [];
  const handshake = new ReceiverRefreshHandshake({
    unready: () => events.push("unready"),
    ready: () => events.push("receiver-ready"),
    viewReady: () => events.push("view-ready"),
  });

  handshake.begin();
  handshake.begin();
  expect(handshake.active).toBe(true);
  expect(events).toEqual(["unready"]);

  handshake.complete();
  handshake.complete();
  expect(handshake.active).toBe(false);
  expect(events).toEqual(["unready", "receiver-ready", "view-ready"]);
});

test("a released refresh cannot publish late readiness", () => {
  const callbacks = {
    unready: vi.fn(),
    ready: vi.fn(),
    viewReady: vi.fn(),
  };
  const handshake = new ReceiverRefreshHandshake(callbacks);

  handshake.begin();
  handshake.release();
  handshake.complete();

  expect(callbacks.unready).toHaveBeenCalledOnce();
  expect(callbacks.ready).not.toHaveBeenCalled();
  expect(callbacks.viewReady).not.toHaveBeenCalled();
});
