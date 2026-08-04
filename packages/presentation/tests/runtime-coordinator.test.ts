import type { RuntimeConfig } from "@marimo-studio/protocol/runtime-config";
import type { RuntimeRegistry, RuntimeSession } from "@marimo-studio/runtime";

import { afterEach, describe, expect, it, vi } from "vite-plus/test";

import {
  disposeConfiguredRuntime,
  mountConfiguredRuntime,
  RuntimeMountCancelledError,
  updateConfiguredRuntime,
  updateConfiguredRuntimeQuery,
} from "../src/runtime/coordinator";

const config = (instance: string): RuntimeConfig =>
  ({ runtime: { id: "test", instance, available: ["test"], data: {} } }) as RuntimeConfig;

describe("runtime coordinator", () => {
  afterEach(disposeConfiguredRuntime);

  it("queues presentation refreshes while the runtime mounts", async () => {
    let finishMount = (_session: RuntimeSession) => {};
    const mounted = new Promise<RuntimeSession>((resolve) => {
      finishMount = resolve;
    });
    const update = vi.fn<RuntimeSession["update"]>(() => "applied");
    const session: RuntimeSession = {
      id: "test",
      update,
      updateQuery: async () => {},
      dispose: vi.fn(),
    };
    const registry = {
      get: () => ({ mount: () => mounted }),
    } as unknown as RuntimeRegistry;

    const mounting = mountConfiguredRuntime(registry, config("first"), {} as HTMLElement);

    expect(updateConfiguredRuntime(config("latest"))).toBe("pending");
    finishMount(session);
    await mounting;
    expect(updateConfiguredRuntime(config("latest"))).toBe("applied");
    expect(update).toHaveBeenCalledOnce();
  });

  it("disposes a runtime that finishes mounting after teardown", async () => {
    let finishMount = (_session: RuntimeSession) => {};
    const mounted = new Promise<RuntimeSession>((resolve) => {
      finishMount = resolve;
    });
    const session: RuntimeSession = {
      id: "test",
      update: () => "applied",
      updateQuery: async () => {},
      dispose: vi.fn(),
    };
    const registry = {
      get: () => ({ mount: () => mounted }),
    } as unknown as RuntimeRegistry;
    const mounting = mountConfiguredRuntime(registry, config("first"), {} as HTMLElement);

    disposeConfiguredRuntime();
    finishMount(session);

    await expect(mounting).rejects.toBeInstanceOf(RuntimeMountCancelledError);
    expect(session.dispose).toHaveBeenCalledOnce();
    expect(updateConfiguredRuntime(config("latest"))).toBe("pending");
  });

  it("delegates query changes to the mounted runtime", async () => {
    const updateQuery = vi.fn(async () => {});
    const session: RuntimeSession = {
      id: "test",
      update: () => "applied",
      updateQuery,
      dispose: vi.fn(),
    };
    const registry = {
      get: () => ({ mount: async () => session }),
    } as unknown as RuntimeRegistry;

    await mountConfiguredRuntime(registry, config("first"), {} as HTMLElement);
    await updateConfiguredRuntimeQuery("?region=emea");

    expect(updateQuery).toHaveBeenCalledWith("?region=emea");
  });
});
