import { afterEach, describe, expect, it, vi } from "vite-plus/test";

import { createStudioServices } from "../src/app/services.ts";
import { viewList } from "./fixtures.ts";
import { deferred, studioBootstrap as bootstrap, studioFrames } from "./studio-test-support.ts";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("Studio view handoff lifecycle", () => {
  it("suspends the old agent target before a committed view becomes current", async () => {
    let agentTarget: "dashboard" | "unavailable" | "report" = "dashboard";
    class EventSourceStub {
      static instances: EventSourceStub[] = [];
      readonly listeners = new Map<string, EventListener>();

      constructor(readonly url: string) {
        EventSourceStub.instances.push(this);
      }

      addEventListener(type: string, listener: EventListener): void {
        this.listeners.set(type, listener);
      }

      emit(type: string, data: string): void {
        if (type === "ready" && this.url.includes("marimo_studio_view=report")) {
          agentTarget = "report";
        }
        this.listeners.get(type)?.(new MessageEvent(type, { data }));
      }

      close(): void {}
    }

    vi.stubGlobal("EventSource", EventSourceStub);
    const handoffResponse = deferred<Response>();
    const request = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(input instanceof Request ? input.url : String(input), location.href);
      if (url.pathname === "/_marimo-studio/views") {
        return Response.json(viewList(["dashboard", "report"]));
      }
      if (url.pathname.includes("/active-view-handoffs/") && init?.method === "POST") {
        agentTarget = "unavailable";
        return await handoffResponse.promise;
      }
      throw new Error(`Unexpected request ${init?.method ?? "GET"} ${url}`);
    });
    vi.stubGlobal("fetch", request);
    const services = createStudioServices(bootstrap);
    vi.spyOn(services.source, "start").mockResolvedValue();
    await services.start(document.createElement("iframe"), studioFrames());
    const rollback = vi.fn(async () => undefined);
    const commit = vi.fn();
    vi.spyOn(services.preview, "stageNavigation")
      .mockReturnValueOnce({ ready: Promise.resolve(false), commit, rollback })
      .mockReturnValueOnce({ ready: Promise.resolve(true), commit, rollback });

    expect(await services.views.choose("report")).toBe(false);
    expect(services.views.getSnapshot().current).toBe("dashboard");
    expect(agentTarget).toBe("dashboard");
    expect(EventSourceStub.instances).toHaveLength(1);
    const requestedHandoff = () =>
      request.mock.calls.some(([input]) => {
        let url: string;
        if (input instanceof Request) {
          url = input.url;
        } else if (input instanceof URL) {
          url = input.href;
        } else {
          url = input;
        }
        return url.includes("active-view-handoffs");
      });
    expect(requestedHandoff()).toBe(false);

    const choosing = services.views.choose("report");
    await vi.waitFor(() => expect(requestedHandoff()).toBe(true));
    expect(services.views.getSnapshot().current).toBe("dashboard");
    expect(agentTarget).toBe("unavailable");
    expect(EventSourceStub.instances).toHaveLength(1);

    handoffResponse.resolve(new Response(null, { status: 204 }));
    expect(await choosing).toBe(true);
    expect(services.views.getSnapshot().current).toBe("report");
    expect(agentTarget).toBe("unavailable");
    expect(EventSourceStub.instances).toHaveLength(2);

    EventSourceStub.instances[1]?.emit(
      "ready",
      JSON.stringify({ schema: 1, view: "report", revision: "revision-report" }),
    );
    expect(agentTarget).toBe("report");
    await services.close();
  });

  it("recovers the committed view after the finite release budget", async () => {
    vi.useFakeTimers();
    let handoffActive = false;
    let deleteAttempts = 0;
    class EventSourceStub {
      static instances: EventSourceStub[] = [];
      readonly listeners = new Map<string, EventListener>();
      closed = false;

      constructor(readonly url: string) {
        EventSourceStub.instances.push(this);
        if (EventSourceStub.instances.length > 1 && url.includes("marimo_studio_view=dashboard")) {
          handoffActive = false;
        }
      }

      addEventListener(type: string, listener: EventListener): void {
        this.listeners.set(type, listener);
      }

      emit(type: string, data: string): void {
        this.listeners.get(type)?.(new MessageEvent(type, { data }));
      }

      close(): void {
        this.closed = true;
      }
    }
    vi.stubGlobal("EventSource", EventSourceStub);
    let holdAcquisition = true;
    const request = vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const url = new URL(input instanceof Request ? input.url : String(input), location.href);
      if (url.pathname === "/_marimo-studio/views") {
        return Promise.resolve(Response.json(viewList(["dashboard", "report"])));
      }
      if (!url.pathname.includes("/active-view-handoffs/")) {
        throw new Error(`Unexpected request ${init?.method ?? "GET"} ${url}`);
      }
      if (init?.method === "POST") {
        handoffActive = true;
        if (holdAcquisition) {
          holdAcquisition = false;
          return new Promise<Response>((_resolve, reject) => {
            init.signal?.addEventListener("abort", () =>
              reject(new DOMException("Aborted", "AbortError")),
            );
          });
        }
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      deleteAttempts += 1;
      return Promise.resolve(new Response(null, { status: 503 }));
    });
    vi.stubGlobal("fetch", request);
    const services = createStudioServices(bootstrap);
    vi.spyOn(services.source, "start").mockResolvedValue();
    vi.spyOn(services.preview, "stageNavigation").mockReturnValue({
      ready: Promise.resolve(true),
      rollback: async () => undefined,
    });
    await services.start(document.createElement("iframe"), studioFrames());
    const report = services.views.choose("report");
    await vi.waitFor(() => expect(handoffActive).toBe(true));
    let dashboardSettled = false;
    const dashboard = services.views.choose("dashboard").then((selected) => {
      dashboardSettled = true;
      return selected;
    });

    for (const delay of [100, 300, 1_000, 3_000, 5_000]) {
      await vi.advanceTimersByTimeAsync(delay);
    }
    await vi.waitFor(() => expect(EventSourceStub.instances).toHaveLength(2));
    expect(deleteAttempts).toBe(6);
    expect(EventSourceStub.instances[0]?.closed).toBe(true);
    expect(handoffActive).toBe(false);
    expect(dashboardSettled).toBe(false);

    EventSourceStub.instances[1]?.emit(
      "ready",
      JSON.stringify({ schema: 1, view: "dashboard", revision: "revision-dashboard" }),
    );

    expect(await report).toBe(false);
    expect(await dashboard).toBe(true);
    expect(services.views.getSnapshot().current).toBe("dashboard");
    await services.close();
  });

  it.each([204, 409] as const)(
    "recovers from rejected acquisition after DELETE %s",
    async (cleanupStatus) => {
      let acquisitionBlocked = true;
      let handoffActive = cleanupStatus === 409;
      class EventSourceStub {
        static instances: EventSourceStub[] = [];
        readonly listeners = new Map<string, EventListener>();

        constructor(readonly url: string) {
          EventSourceStub.instances.push(this);
          if (
            EventSourceStub.instances.length > 1 &&
            (url.includes("marimo_studio_view=dashboard") ||
              url.includes("marimo_studio_view=report"))
          ) {
            acquisitionBlocked = false;
            handoffActive = false;
          }
        }

        addEventListener(type: string, listener: EventListener): void {
          this.listeners.set(type, listener);
        }

        emit(type: string, data: string): void {
          this.listeners.get(type)?.(new MessageEvent(type, { data }));
        }

        close(): void {}
      }
      vi.stubGlobal("EventSource", EventSourceStub);
      const request = vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = new URL(input instanceof Request ? input.url : String(input), location.href);
        if (url.pathname === "/_marimo-studio/views") {
          return Promise.resolve(Response.json(viewList(["dashboard", "report"])));
        }
        if (!url.pathname.includes("/active-view-handoffs/")) {
          throw new Error(`Unexpected request ${init?.method ?? "GET"} ${url}`);
        }
        if (init?.method === "POST") {
          if (acquisitionBlocked || handoffActive) {
            return Promise.resolve(new Response(null, { status: 409 }));
          }
          handoffActive = true;
          return Promise.resolve(new Response(null, { status: 204 }));
        }
        return Promise.resolve(new Response(null, { status: cleanupStatus }));
      });
      vi.stubGlobal("fetch", request);
      const services = createStudioServices(bootstrap);
      vi.spyOn(services.source, "start").mockResolvedValue();
      vi.spyOn(services.preview, "stageNavigation").mockReturnValue({
        ready: Promise.resolve(true),
        rollback: async () => undefined,
      });
      await services.start(document.createElement("iframe"), studioFrames());

      const rejected = services.views.choose("report");
      await vi.waitFor(() => expect(EventSourceStub.instances).toHaveLength(2));
      expect(acquisitionBlocked).toBe(false);
      expect(handoffActive).toBe(false);
      EventSourceStub.instances[1]?.emit(
        "ready",
        JSON.stringify({ schema: 1, view: "dashboard", revision: "revision-dashboard" }),
      );
      expect(await rejected).toBe(false);

      expect(await services.views.choose("report")).toBe(true);
      expect(services.views.getSnapshot().current).toBe("report");
      expect(handoffActive).toBe(false);
      expect(EventSourceStub.instances).toHaveLength(3);
      await services.close();
    },
  );

  it("drains a staged handoff before same-client remount", async () => {
    const events: string[] = [];
    const previewCanSettle = deferred<void>();
    let handoffActive = false;
    class EventSourceStub {
      static instances: EventSourceStub[] = [];

      constructor(readonly url: string) {
        EventSourceStub.instances.push(this);
        if (url.includes("marimo_studio_view=report")) {
          handoffActive = false;
          events.push("report-stream-promoted");
        }
      }

      addEventListener(): void {}

      close(): void {
        events.push("stream-closed");
      }
    }
    vi.stubGlobal("EventSource", EventSourceStub);
    let holdFirstPost = true;
    const request = vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const url = new URL(input instanceof Request ? input.url : String(input), location.href);
      if (url.pathname === "/_marimo-studio/views") {
        return Promise.resolve(Response.json(viewList(["dashboard", "report"])));
      }
      if (!url.pathname.includes("/active-view-handoffs/")) {
        throw new Error(`Unexpected request ${init?.method ?? "GET"} ${url}`);
      }
      if (init?.method === "POST") {
        if (handoffActive) {
          return Promise.resolve(new Response(null, { status: 409 }));
        }
        handoffActive = true;
        events.push("handoff-acquired");
        if (holdFirstPost) {
          holdFirstPost = false;
          return new Promise<Response>((_resolve, reject) => {
            init.signal?.addEventListener("abort", () =>
              reject(new DOMException("Aborted", "AbortError")),
            );
          });
        }
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      handoffActive = false;
      events.push("handoff-released");
      previewCanSettle.resolve();
      return Promise.resolve(new Response(null, { status: 204 }));
    });
    vi.stubGlobal("fetch", request);
    const first = createStudioServices(bootstrap);
    vi.spyOn(first.source, "start").mockResolvedValue();
    const firstPreviewRollback = vi.fn(async () => {
      events.push("preview-restoration-started");
      await previewCanSettle.promise;
      events.push("preview-restored");
    });
    vi.spyOn(first.preview, "stageNavigation").mockReturnValue({
      ready: Promise.resolve(true),
      rollback: firstPreviewRollback,
    });
    await first.start(document.createElement("iframe"), studioFrames());
    const selecting = first.views.choose("report");
    await vi.waitFor(() => expect(handoffActive).toBe(true));

    await first.close();
    expect(await selecting).toBe(false);

    expect(handoffActive).toBe(false);
    expect(events.indexOf("preview-restoration-started")).toBeLessThan(
      events.indexOf("handoff-released"),
    );
    expect(events.indexOf("handoff-released")).toBeLessThan(events.indexOf("preview-restored"));
    expect(events.indexOf("preview-restored")).toBeLessThan(events.indexOf("stream-closed"));

    const second = createStudioServices(bootstrap);
    vi.spyOn(second.source, "start").mockResolvedValue();
    vi.spyOn(second.preview, "stageNavigation").mockReturnValue({
      ready: Promise.resolve(true),
      rollback: async () => undefined,
    });
    await second.start(document.createElement("iframe"), studioFrames());

    expect(await second.views.choose("report")).toBe(true);
    expect(second.views.getSnapshot().current).toBe("report");
    expect(handoffActive).toBe(false);
    expect(events).toContain("report-stream-promoted");
    await second.close();
  });

  it("bounds close reconciliation and falls back to stream disconnect", async () => {
    vi.useFakeTimers();
    let handoffActive = false;
    let holdAcquisition = true;
    let deleteAttempts = 0;
    class EventSourceStub {
      constructor(readonly url: string) {
        if (url.includes("marimo_studio_view=report")) {
          handoffActive = false;
        }
      }

      addEventListener(): void {}

      close(): void {
        handoffActive = false;
      }
    }
    vi.stubGlobal("EventSource", EventSourceStub);
    const request = vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const url = new URL(input instanceof Request ? input.url : String(input), location.href);
      if (url.pathname === "/_marimo-studio/views") {
        return Promise.resolve(Response.json(viewList(["dashboard", "report"])));
      }
      if (!url.pathname.includes("/active-view-handoffs/")) {
        throw new Error(`Unexpected request ${init?.method ?? "GET"} ${url}`);
      }
      if (init?.method === "POST") {
        if (handoffActive) {
          return Promise.resolve(new Response(null, { status: 409 }));
        }
        handoffActive = true;
        if (holdAcquisition) {
          holdAcquisition = false;
          return new Promise<Response>((_resolve, reject) => {
            init.signal?.addEventListener("abort", () =>
              reject(new DOMException("Aborted", "AbortError")),
            );
          });
        }
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      deleteAttempts += 1;
      return Promise.resolve(new Response(null, { status: 503 }));
    });
    vi.stubGlobal("fetch", request);
    const first = createStudioServices(bootstrap);
    vi.spyOn(first.source, "start").mockResolvedValue();
    const sourceDispose = vi.spyOn(first.source, "dispose");
    const previewDispose = vi.spyOn(first.preview, "dispose");
    const layoutDispose = vi.spyOn(first.layout, "dispose");
    const neverPreview = new Promise<void>(() => {});
    vi.spyOn(first.preview, "stageNavigation").mockReturnValue({
      ready: Promise.resolve(true),
      rollback: () => neverPreview,
    });
    await first.start(document.createElement("iframe"), studioFrames());
    const selecting = first.views.choose("report");
    await vi.waitFor(() => expect(handoffActive).toBe(true));

    let closed = false;
    const closing = first.close().then(() => {
      closed = true;
    });
    await vi.advanceTimersByTimeAsync(2_999);
    expect(closed).toBe(false);
    expect(sourceDispose).not.toHaveBeenCalled();
    expect(previewDispose).not.toHaveBeenCalled();
    expect(layoutDispose).not.toHaveBeenCalled();
    expect(deleteAttempts).toBeGreaterThan(2);
    const attemptsBeforeDeadline = deleteAttempts;

    await vi.advanceTimersByTimeAsync(1);
    await closing;
    expect(closed).toBe(true);
    expect(await selecting).toBe(false);
    expect(handoffActive).toBe(false);
    expect(sourceDispose).toHaveBeenCalledOnce();
    expect(previewDispose).toHaveBeenCalledOnce();
    expect(layoutDispose).toHaveBeenCalledOnce();
    expect(deleteAttempts).toBe(attemptsBeforeDeadline);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(deleteAttempts).toBe(attemptsBeforeDeadline);

    const second = createStudioServices(bootstrap);
    vi.spyOn(second.source, "start").mockResolvedValue();
    vi.spyOn(second.preview, "stageNavigation").mockReturnValue({
      ready: Promise.resolve(true),
      rollback: async () => undefined,
    });
    await second.start(document.createElement("iframe"), studioFrames());

    expect(await second.views.choose("report")).toBe(true);
    expect(second.views.getSnapshot().current).toBe("report");
    expect(handoffActive).toBe(false);
    await second.close();
  });

  it("restores an agent-owned view after activation acknowledgement is rejected", async () => {
    globalThis.history.replaceState({}, "", "/studio/dashboard/");
    class ActivationEventSourceStub {
      static instances: ActivationEventSourceStub[] = [];
      readonly listeners = new Map<string, EventListener>();
      closed = false;

      constructor(readonly url: string) {
        ActivationEventSourceStub.instances.push(this);
      }

      addEventListener(type: string, listener: EventListener): void {
        this.listeners.set(type, listener);
      }

      emit(type: string, data: string): void {
        this.listeners.get(type)?.(new MessageEvent(type, { data }));
      }

      close(): void {
        this.closed = true;
      }
    }

    vi.stubGlobal("EventSource", ActivationEventSourceStub);
    const request = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(input instanceof Request ? input.url : String(input), location.href);
      if (url.pathname === "/_marimo-studio/views") {
        return Response.json(viewList(["dashboard", "report"]));
      }
      if (url.pathname.endsWith("/activations/9/ack") && init?.method === "POST") {
        return Response.json({ schema: 1, outcome: "rejected" }, { status: 409 });
      }
      throw new Error(`Unexpected request ${init?.method ?? "GET"} ${url}`);
    });
    vi.stubGlobal("fetch", request);
    const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const services = createStudioServices(bootstrap);
    vi.spyOn(services.source, "start").mockResolvedValue();
    const frames = new Map(
      services.previewFrameIds.map((id) => [id, document.createElement("iframe")]),
    );
    await services.start(document.createElement("iframe"), frames);
    const stageNavigation = vi.spyOn(services.preview, "stageNavigation").mockReturnValue({
      ready: Promise.resolve(true),
      commit: vi.fn(),
      rollback: vi.fn(async () => undefined),
    });

    ActivationEventSourceStub.instances[0]?.emit(
      "activate",
      JSON.stringify({ schema: 1, generation: 9, view: "report" }),
    );

    await vi.waitFor(() => expect(stageNavigation).toHaveBeenCalledTimes(2));
    expect(stageNavigation.mock.calls.map(([view]) => view)).toEqual(["report", "dashboard"]);
    expect(services.views.getSnapshot().current).toBe("dashboard");
    expect(services.source.getSnapshot().view).toBe("dashboard");
    expect(globalThis.location.pathname).toBe("/studio/dashboard/");
    expect(
      services.preview
        .getSnapshot()
        .frames.some(({ active, view }) => active && view === "dashboard"),
    ).toBe(true);
    expect(ActivationEventSourceStub.instances).toHaveLength(3);
    expect(ActivationEventSourceStub.instances[1]?.closed).toBe(true);
    expect(ActivationEventSourceStub.instances[2]?.url).toContain("marimo_studio_view=dashboard");
    expect(
      request.mock.calls.some(([input]) =>
        String(input instanceof Request ? input.url : input).includes("active-view-handoffs"),
      ),
    ).toBe(false);
    expect(
      request.mock.calls.some(([input]) =>
        String(input instanceof Request ? input.url : input).includes("/activations/9/ack"),
      ),
    ).toBe(true);

    warning.mockRestore();
    await services.close();
  });
});
