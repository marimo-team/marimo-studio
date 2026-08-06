import { beforeEach, describe, expect, it, vi } from "vite-plus/test";

import type { ViewRemote } from "../src/features/views/remote.ts";

import { SourceController } from "../src/features/source-editor/controller.ts";
import { ViewController } from "../src/features/views/controller.ts";

const deferred = <T>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
};

class EventSourceStub {
  static latest: EventSourceStub | undefined;
  static opened = 0;

  private readonly listeners = new Map<string, EventListener>();

  constructor(readonly url: string) {
    EventSourceStub.latest = this;
    EventSourceStub.opened += 1;
  }

  addEventListener(type: string, listener: EventListener): void {
    this.listeners.set(type, listener);
  }

  emit(type: string): void {
    this.listeners.get(type)?.(new Event(type));
  }

  close(): void {}
}

beforeEach(() => {
  EventSourceStub.latest = undefined;
  EventSourceStub.opened = 0;
  vi.stubGlobal("EventSource", EventSourceStub);
});

describe("controller lifecycle", () => {
  it("does not open source events after disposal during initial reads", async () => {
    const html = deferred<Response>();
    const css = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementationOnce(() => html.promise)
        .mockImplementationOnce(() => css.promise),
    );
    const source = new SourceController("/views", "token", "dashboard", "workspace", vi.fn());

    const starting = source.start();
    source.dispose();
    html.resolve(new Response("<main />", { headers: { ETag: '"html-1"' } }));
    css.resolve(new Response("body {}", { headers: { ETag: '"css-1"' } }));
    await starting;

    expect(EventSourceStub.opened).toBe(0);
  });

  it("ignores a view list loaded before a successful create", async () => {
    const listing = deferred<Awaited<ReturnType<ViewRemote["list"]>>>();
    const canonical = {
      schema: 1 as const,
      default_view: "dashboard",
      views: ["dashboard", "report"],
    };
    const remote: ViewRemote = {
      list: vi
        .fn()
        .mockImplementationOnce(() => listing.promise)
        .mockResolvedValue(canonical),
      create: vi.fn(async (name: string) => ({ schema: 1 as const, name })),
      remove: vi.fn(),
    };
    const controller = new ViewController(
      "dashboard",
      ["dashboard"],
      remote,
      "/events",
      vi.fn(async () => true),
      vi.fn(async () => true),
      vi.fn(),
    );
    controller.start();
    EventSourceStub.latest?.emit("ready");
    await Promise.resolve();

    expect(await controller.create("report")).toBe(true);
    listing.resolve({ schema: 1, default_view: "dashboard", views: ["dashboard"] });
    await Promise.resolve();

    expect(controller.getSnapshot().views).toEqual(["dashboard", "report"]);
    expect(controller.getSnapshot().current).toBe("report");
    controller.dispose();
  });

  it("does not select a view after a pending refresh is disposed", async () => {
    const listing = deferred<Awaited<ReturnType<ViewRemote["list"]>>>();
    const select = vi.fn(async () => true);
    const remote: ViewRemote = {
      list: vi.fn(() => listing.promise),
      create: vi.fn(),
      remove: vi.fn(),
    };
    const controller = new ViewController(
      "dashboard",
      ["dashboard"],
      remote,
      "/events",
      select,
      vi.fn(async () => true),
      vi.fn(),
    );
    controller.start();
    EventSourceStub.latest?.emit("ready");
    await Promise.resolve();

    controller.dispose();
    listing.resolve({ schema: 1, default_view: "report", views: ["report"] });
    await Promise.resolve();

    expect(select).not.toHaveBeenCalled();
  });

  it("retargets the active view before deleting its files", async () => {
    const order: string[] = [];
    let removed = false;
    const remote: ViewRemote = {
      list: vi.fn(async () => {
        order.push("list");
        return removed
          ? { schema: 1 as const, default_view: "report", views: ["report"] }
          : {
              schema: 1 as const,
              default_view: "dashboard",
              views: ["dashboard", "report"],
            };
      }),
      create: vi.fn(),
      remove: vi.fn(async (name: string) => {
        order.push(`remove:${name}`);
        removed = true;
        return {
          schema: 1 as const,
          name,
          default_view: "report",
          views: ["report"],
        };
      }),
    };
    const controller = new ViewController(
      "dashboard",
      ["dashboard", "report"],
      remote,
      "/events",
      vi.fn(async (view: string) => {
        order.push(`select:${view}`);
        return true;
      }),
      vi.fn(async () => {
        order.push("prepare");
        return true;
      }),
      vi.fn(),
    );

    controller.beginRemoval("dashboard");
    expect(await controller.deleteSelected()).toBe(true);

    expect(order.slice(0, 4)).toEqual(["prepare", "list", "select:report", "remove:dashboard"]);
    expect(controller.getSnapshot().current).toBe("report");
    expect(controller.getSnapshot().views).toEqual(["report"]);
    controller.dispose();
  });

  it("keeps active files when the successor cannot be prepared", async () => {
    const remote: ViewRemote = {
      list: vi.fn(async () => ({
        schema: 1 as const,
        default_view: "dashboard",
        views: ["dashboard", "report"],
      })),
      create: vi.fn(),
      remove: vi.fn(),
    };
    const controller = new ViewController(
      "dashboard",
      ["dashboard", "report"],
      remote,
      "/events",
      vi.fn(async () => false),
      vi.fn(async () => true),
      vi.fn(),
    );

    controller.beginRemoval("dashboard");
    expect(await controller.deleteSelected()).toBe(false);

    expect(remote.remove).not.toHaveBeenCalled();
    expect(controller.getSnapshot().current).toBe("dashboard");
    expect(controller.getSnapshot().removeError).toBe(
      "Select another view before removing this one.",
    );
    controller.dispose();
  });
});
