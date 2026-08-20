import type { RuntimeConfig } from "@marimo-studio/protocol/runtime-config";
import type { RuntimeSession } from "@marimo-studio/runtime";

import { createRuntimeRegistry } from "@marimo-studio/runtime";
import { afterEach, describe, expect, it, vi } from "vite-plus/test";

import { commitRuntimeConfig, getRuntimeConfig } from "../src/runtime-config/index.ts";
import {
  disposeConfiguredRuntime,
  mountConfiguredRuntime,
  beginConfiguredRuntimeRevision,
  RuntimeMountCancelledError,
  updateConfiguredRuntime,
  updateConfiguredRuntimeQuery,
} from "../src/runtime/coordinator";
import { symbolicRuntimeFields } from "./runtime-fixtures";

const descriptor = {
  id: "test",
  label: "Test",
  description: "Runs test projections",
  execution: "prepared" as const,
  projections: { cell: true, output: true, value: true },
  controls: "none" as const,
  query: "none" as const,
  preparation: "on-select" as const,
  session: "none" as const,
};

const config = (instance: string): RuntimeConfig => ({
  schema: 1,
  revision: "revision-a",
  view: "dashboard",
  views: ["dashboard"],
  runtime: { id: "test", instance, data: {} },
  rootUrl: "/",
  publicRootUrl: "/",
  documentRootUrl: "/",
  supportUrl: "/_marimo-studio/views/dashboard",
  showCellLogs: true,
  ...symbolicRuntimeFields,
  diagnostics: [],
  appConfig: {},
  userConfig: {},
  configOverrides: {},
  dev: false,
  mode: "run",
});

type RuntimeApply = (config: RuntimeConfig, signal: AbortSignal) => Promise<"applied" | "reload">;

interface RuntimeSessionOptions {
  apply?: RuntimeApply;
  updateQuery?: RuntimeSession["updateQuery"];
  dispose?: RuntimeSession["dispose"];
}

const runtimeSession = (options: RuntimeSessionOptions = {}): RuntimeSession => {
  const apply = options.apply ?? (async () => "applied" as const);
  const session: RuntimeSession = {
    id: "test",
    beginRevision: async (signal) => ({
      apply: (next) => apply(next, signal),
      commit: async () => {},
      rollback: async () => {},
    }),
    dispose: options.dispose ?? vi.fn(),
  };
  return options.updateQuery === undefined
    ? session
    : { ...session, updateQuery: options.updateQuery };
};

describe("runtime coordinator", () => {
  afterEach(async () => await disposeConfiguredRuntime());

  it("queues presentation refreshes while the runtime mounts", async () => {
    let finishMount = (_session: RuntimeSession) => {};
    const mounted = new Promise<RuntimeSession>((resolve) => {
      finishMount = resolve;
    });
    const update = vi.fn<RuntimeApply>(async () => "applied");
    const session = runtimeSession({ apply: update, updateQuery: async () => {} });
    const registry = createRuntimeRegistry([{ descriptor, mount: () => mounted }]);

    const mounting = mountConfiguredRuntime(
      registry,
      config("first"),
      document.createElement("div"),
    );

    await expect(updateConfiguredRuntime(config("latest"))).resolves.toBe("pending");
    finishMount(session);
    await mounting;
    await expect(updateConfiguredRuntime(config("latest"))).resolves.toBe("applied");
    expect(update).toHaveBeenCalledOnce();
  });

  it("commits instances reported by the active runtime", async () => {
    const initial = config("first");
    commitRuntimeConfig(initial);
    let commitRuntimeInstance = (_instance: string) => {};
    const registry = createRuntimeRegistry([
      {
        descriptor,
        mount: async (context) => {
          commitRuntimeInstance = context.commitRuntimeInstance;
          return runtimeSession();
        },
      },
    ]);

    await mountConfiguredRuntime(registry, initial, document.createElement("div"));
    commitRuntimeInstance("rotated");
    expect(getRuntimeConfig().runtime.instance).toBe("rotated");

    await disposeConfiguredRuntime();
    commitRuntimeInstance("stale");
    expect(getRuntimeConfig().runtime.instance).toBe("rotated");
  });

  it("disposes a runtime that finishes mounting after teardown", async () => {
    let finishMount = (_session: RuntimeSession) => {};
    const mounted = new Promise<RuntimeSession>((resolve) => {
      finishMount = resolve;
    });
    const session = runtimeSession({ updateQuery: async () => {} });
    let mountSignal: AbortSignal | undefined;
    const registry = createRuntimeRegistry([
      {
        descriptor,
        mount: (context) => {
          mountSignal = context.signal;
          return mounted;
        },
      },
    ]);
    const mounting = mountConfiguredRuntime(
      registry,
      config("first"),
      document.createElement("div"),
    );

    await vi.waitFor(() => expect(mountSignal).toBeDefined());
    const disposing = disposeConfiguredRuntime();
    expect(mountSignal?.aborted).toBe(true);
    finishMount(session);
    await disposing;

    await expect(mounting).rejects.toBeInstanceOf(RuntimeMountCancelledError);
    expect(session.dispose).toHaveBeenCalledOnce();
    await expect(updateConfiguredRuntime(config("latest"))).resolves.toBe("pending");
  });

  it("awaits asynchronous cleanup for a stale mounted runtime", async () => {
    let finishMount = (_session: RuntimeSession) => {};
    let finishCleanup = () => {};
    const mounted = new Promise<RuntimeSession>((resolve) => {
      finishMount = resolve;
    });
    const cleanup = new Promise<void>((resolve) => {
      finishCleanup = resolve;
    });
    const dispose = vi.fn(() => cleanup);
    const mount = vi.fn(() => mounted);
    const registry = createRuntimeRegistry([{ descriptor, mount }]);
    const mounting = mountConfiguredRuntime(
      registry,
      config("first"),
      document.createElement("div"),
    );
    const cancelled = mounting.then(
      () => expect.unreachable("The stale runtime mount resolved"),
      (error: RuntimeMountCancelledError) =>
        expect(error).toBeInstanceOf(RuntimeMountCancelledError),
    );

    await vi.waitFor(() => expect(mount).toHaveBeenCalledOnce());
    const disposing = disposeConfiguredRuntime();
    finishMount(runtimeSession({ dispose }));
    await vi.waitFor(() => expect(dispose).toHaveBeenCalledOnce());
    finishCleanup();

    await disposing;
    await cancelled;
  });

  it("serializes two superseding mounts behind pending runtime disposal", async () => {
    let finishCleanup = () => {};
    const cleanup = new Promise<void>((resolve) => {
      finishCleanup = resolve;
    });
    const firstDispose = vi.fn(() => cleanup);
    const finalDispose = vi.fn(async () => {});
    const mountedInstances: string[] = [];
    const registry = createRuntimeRegistry([
      {
        descriptor,
        mount: async ({ presentation }) => {
          mountedInstances.push(presentation.runtime.instance);
          return runtimeSession({
            dispose: presentation.runtime.instance === "first" ? firstDispose : finalDispose,
          });
        },
      },
    ]);
    await mountConfiguredRuntime(registry, config("first"), document.createElement("div"));

    const superseded = mountConfiguredRuntime(
      registry,
      config("second"),
      document.createElement("div"),
    );
    await vi.waitFor(() => expect(firstDispose).toHaveBeenCalledOnce());
    const selected = mountConfiguredRuntime(
      registry,
      config("third"),
      document.createElement("div"),
    );

    expect(mountedInstances).toEqual(["first"]);
    finishCleanup();
    await expect(superseded).rejects.toBeInstanceOf(RuntimeMountCancelledError);
    await selected;
    expect(mountedInstances).toEqual(["first", "third"]);
  });

  it("waits for an active update before disposing its runtime", async () => {
    let finishUpdate = (_result: "applied") => {};
    const updating = new Promise<"applied">((resolve) => {
      finishUpdate = resolve;
    });
    const update = vi.fn(() => updating);
    const dispose = vi.fn(async () => {});
    const registry = createRuntimeRegistry([
      {
        descriptor,
        mount: async () => runtimeSession({ apply: update, dispose }),
      },
    ]);
    await mountConfiguredRuntime(registry, config("first"), document.createElement("div"));

    const refreshing = updateConfiguredRuntime(config("updated"));
    await vi.waitFor(() => expect(update).toHaveBeenCalledOnce());
    const disposing = disposeConfiguredRuntime();
    await Promise.resolve();
    expect(dispose).not.toHaveBeenCalled();
    finishUpdate("applied");

    await expect(refreshing).rejects.toMatchObject({ name: "AbortError" });
    await disposing;
    expect(dispose).toHaveBeenCalledOnce();
  });

  it("waits for an active update before mounting a superseding runtime", async () => {
    let finishUpdate = (_result: "applied") => {};
    const updating = new Promise<"applied">((resolve) => {
      finishUpdate = resolve;
    });
    const update = vi.fn(() => updating);
    const firstDispose = vi.fn(async () => {});
    const mounted: string[] = [];
    const registry = createRuntimeRegistry([
      {
        descriptor,
        mount: async ({ presentation }) => {
          mounted.push(presentation.runtime.instance);
          return runtimeSession({
            apply:
              presentation.runtime.instance === "first" ? update : async () => "applied" as const,
            dispose: firstDispose,
          });
        },
      },
    ]);
    await mountConfiguredRuntime(registry, config("first"), document.createElement("div"));

    const refreshing = updateConfiguredRuntime(config("updated"));
    await vi.waitFor(() => expect(update).toHaveBeenCalledOnce());
    const mounting = mountConfiguredRuntime(
      registry,
      config("second"),
      document.createElement("div"),
    );
    await Promise.resolve();
    expect(mounted).toEqual(["first"]);
    expect(firstDispose).not.toHaveBeenCalled();
    finishUpdate("applied");

    await expect(refreshing).rejects.toMatchObject({ name: "AbortError" });
    await mounting;
    expect(firstDispose).toHaveBeenCalledOnce();
    expect(mounted).toEqual(["first", "second"]);
  });

  it("waits for an active query before disposing its runtime", async () => {
    let finishQuery = () => {};
    const query = new Promise<void>((resolve) => {
      finishQuery = resolve;
    });
    const updateQuery = vi.fn(() => query);
    const dispose = vi.fn(async () => {});
    const registry = createRuntimeRegistry([
      {
        descriptor,
        mount: async () => runtimeSession({ updateQuery, dispose }),
      },
    ]);
    await mountConfiguredRuntime(registry, config("first"), document.createElement("div"));

    const querying = updateConfiguredRuntimeQuery("?mode=alternate");
    await vi.waitFor(() => expect(updateQuery).toHaveBeenCalledOnce());
    const disposing = disposeConfiguredRuntime();
    await Promise.resolve();
    expect(dispose).not.toHaveBeenCalled();
    finishQuery();

    await expect(querying).rejects.toMatchObject({ name: "AbortError" });
    await disposing;
    expect(dispose).toHaveBeenCalledOnce();
  });

  it("aborts an active query before applying a config update", async () => {
    let finishQuery = () => {};
    const query = new Promise<void>((resolve) => {
      finishQuery = resolve;
    });
    const updateQuery = vi.fn(() => query);
    const update = vi.fn<RuntimeApply>(async () => "applied");
    const registry = createRuntimeRegistry([
      {
        descriptor,
        mount: async () => runtimeSession({ apply: update, updateQuery }),
      },
    ]);
    await mountConfiguredRuntime(registry, config("first"), document.createElement("div"));

    const querying = updateConfiguredRuntimeQuery("?mode=alternate");
    await vi.waitFor(() => expect(updateQuery).toHaveBeenCalledOnce());
    const refreshing = updateConfiguredRuntime(config("updated"));
    await Promise.resolve();
    expect(update).not.toHaveBeenCalled();
    finishQuery();

    await expect(querying).rejects.toMatchObject({ name: "AbortError" });
    await expect(refreshing).resolves.toBe("applied");
    expect(update).toHaveBeenCalledOnce();
  });

  it("settles an abort-aware query before a revision config update", async () => {
    const updateQuery = vi.fn(
      async (_query: string, signal: AbortSignal) =>
        await new Promise<void>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason), { once: true });
        }),
    );
    const update = vi.fn<RuntimeApply>(async () => "applied");
    const registry = createRuntimeRegistry([
      {
        descriptor,
        mount: async () => runtimeSession({ apply: update, updateQuery }),
      },
    ]);
    await mountConfiguredRuntime(registry, config("first"), document.createElement("div"));

    const querying = updateConfiguredRuntimeQuery("?mode=stale");
    const cancelled = expect(querying).rejects.toMatchObject({ name: "AbortError" });
    await vi.waitFor(() => expect(updateQuery).toHaveBeenCalledOnce());
    await expect(updateConfiguredRuntime(config("revision-b"))).resolves.toBe("applied");

    await cancelled;
    expect(update).toHaveBeenCalledOnce();
  });

  it("settles active query cleanup before releasing the document revision barrier", async () => {
    let cleaned = false;
    const updateQuery = vi.fn(
      async (_query: string, signal: AbortSignal) =>
        await new Promise<void>((_resolve, reject) => {
          signal.addEventListener(
            "abort",
            () => {
              setTimeout(() => {
                cleaned = true;
                reject(signal.reason);
              }, 0);
            },
            { once: true },
          );
        }),
    );
    const registry = createRuntimeRegistry([
      {
        descriptor,
        mount: async () => runtimeSession({ updateQuery }),
      },
    ]);
    await mountConfiguredRuntime(registry, config("first"), document.createElement("div"));

    const querying = updateConfiguredRuntimeQuery("?mode=stale");
    const cancelled = expect(querying).rejects.toMatchObject({ name: "AbortError" });
    await vi.waitFor(() => expect(updateQuery).toHaveBeenCalledOnce());
    const revision = await beginConfiguredRuntimeRevision(new AbortController().signal);

    expect(cleaned).toBe(true);
    await revision.commit();
    await cancelled;
  });

  it("aborts a stalled config update before disposing its runtime", async () => {
    const update = vi.fn(
      async (_config: RuntimeConfig, signal: AbortSignal) =>
        await new Promise<"applied">((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason), { once: true });
        }),
    );
    const dispose = vi.fn(async () => {});
    const registry = createRuntimeRegistry([
      { descriptor, mount: async () => runtimeSession({ apply: update, dispose }) },
    ]);
    await mountConfiguredRuntime(registry, config("first"), document.createElement("div"));

    const refreshing = updateConfiguredRuntime(config("updated"));
    const cancelled = expect(refreshing).rejects.toMatchObject({ name: "AbortError" });
    await vi.waitFor(() => expect(update).toHaveBeenCalledOnce());
    await disposeConfiguredRuntime();

    await cancelled;
    expect(dispose).toHaveBeenCalledOnce();
  });

  it("aborts a stalled query before disposing its runtime", async () => {
    const updateQuery = vi.fn(
      async (_query: string, signal: AbortSignal) =>
        await new Promise<void>((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(signal.reason), { once: true });
        }),
    );
    const dispose = vi.fn(async () => {});
    const registry = createRuntimeRegistry([
      {
        descriptor,
        mount: async () => runtimeSession({ updateQuery, dispose }),
      },
    ]);
    await mountConfiguredRuntime(registry, config("first"), document.createElement("div"));

    const querying = updateConfiguredRuntimeQuery("?mode=first");
    const cancelled = expect(querying).rejects.toMatchObject({ name: "AbortError" });
    await vi.waitFor(() => expect(updateQuery).toHaveBeenCalledOnce());
    await disposeConfiguredRuntime();

    await cancelled;
    expect(dispose).toHaveBeenCalledOnce();
  });

  it("coalesces active and pending queries to the latest value", async () => {
    const applied: string[] = [];
    const updateQuery = vi.fn(async (query: string, signal: AbortSignal) => {
      applied.push(query);
      if (query === "?mode=third") {
        return;
      }
      await new Promise<void>((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(signal.reason), { once: true });
      });
    });
    const registry = createRuntimeRegistry([
      {
        descriptor,
        mount: async () => runtimeSession({ updateQuery }),
      },
    ]);
    await mountConfiguredRuntime(registry, config("first"), document.createElement("div"));

    const first = updateConfiguredRuntimeQuery("?mode=first");
    const firstCancelled = expect(first).rejects.toMatchObject({ name: "AbortError" });
    await vi.waitFor(() => expect(updateQuery).toHaveBeenCalledOnce());
    const second = updateConfiguredRuntimeQuery("?mode=second");
    const secondCancelled = expect(second).rejects.toMatchObject({ name: "AbortError" });
    const third = updateConfiguredRuntimeQuery("?mode=third");

    await Promise.all([firstCancelled, secondCancelled, third]);
    expect(applied).toEqual(["?mode=first", "?mode=third"]);
  });

  it("delegates query changes to the mounted runtime", async () => {
    const updateQuery = vi.fn(async () => {});
    const session = runtimeSession({ updateQuery });
    const registry = createRuntimeRegistry([{ descriptor, mount: async () => session }]);

    await mountConfiguredRuntime(registry, config("first"), document.createElement("div"));
    await updateConfiguredRuntimeQuery("?region=emea");

    expect(updateQuery).toHaveBeenCalledWith("?region=emea", expect.any(AbortSignal));
  });

  it("accepts a runtime with no query updater", async () => {
    const registry = createRuntimeRegistry([
      {
        descriptor,
        mount: async () => runtimeSession(),
      },
    ]);

    await mountConfiguredRuntime(registry, config("first"), document.createElement("div"));

    await expect(updateConfiguredRuntimeQuery("?region=emea")).resolves.toBeUndefined();
  });
});
