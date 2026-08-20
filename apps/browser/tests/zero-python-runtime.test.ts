// @vitest-environment jsdom

import { describe, expect, it, vi } from "vite-plus/test";

import { mountZeroPythonRuntime } from "../src/zero-python/mount.ts";
import { ZERO_PYTHON_RUNTIME_DESCRIPTOR, zeroPythonRuntime } from "../src/zero-python/runtime.ts";
import {
  installMarimoStudioGlobal,
  notebookExportFixture,
  rendererFixture,
  runtimeConfig,
  runtimeDependencies,
  runtimeRoot,
  studioManifest,
} from "./zero-python-fixture.ts";

describe("Studio Zero-Python runtime adapter", () => {
  it("registers the prepared runtime descriptor", () => {
    expect(zeroPythonRuntime.descriptor).toEqual(ZERO_PYTHON_RUNTIME_DESCRIPTOR);
    expect(ZERO_PYTHON_RUNTIME_DESCRIPTOR).toEqual({
      id: "zero-python",
      label: "Zero-Python",
      description: "Loads prepared notebook states",
      execution: "prepared",
      projections: { cell: true, output: true, value: true },
      controls: "state",
      query: "state",
      preparation: "on-select",
      session: "none",
    });
  });

  it("mounts through the public prepared API and exposes semantic state updates", async () => {
    installMarimoStudioGlobal();
    const notebookExport = notebookExportFixture({
      inputs: [{ mode: "baseline" }, { mode: "alternate" }],
    });
    const renderer = rendererFixture();
    const config = runtimeConfig();
    const dependencies = runtimeDependencies(
      notebookExport,
      [studioManifest(notebookExport, { mode: "baseline" })],
      renderer.handle,
    );

    const session = await mountZeroPythonRuntime(
      {
        presentation: config,
        root: runtimeRoot(),
        signal: new AbortController().signal,
        commitRuntimeInstance: vi.fn(),
      },
      config.runtime.data,
      dependencies,
    );
    await globalThis.marimoStudio.state?.update({ mode: "alternate" });

    expect(renderer.snapshots).toHaveLength(2);
    expect(globalThis.marimoStudio.state?.inputs()).toEqual({ mode: "alternate" });
    expect(globalThis.marimoStudio.state?.states()).toHaveLength(2);
    expect(dependencies.setConnectionState).toHaveBeenLastCalledWith("ready");
    expect(session.initialQueryApplied).toBe(true);

    await session.dispose();
    expect(globalThis.marimoStudio.state).toBeUndefined();
    expect(renderer.handle.dispose).toHaveBeenCalledOnce();
  });

  it("applies the initial query before reporting the runtime ready", async () => {
    installMarimoStudioGlobal();
    globalThis.history.replaceState({}, "", "?mode=alternate");
    const notebookExport = notebookExportFixture({
      inputs: [{ mode: "baseline" }, { mode: "alternate" }],
    });
    const renderer = rendererFixture();
    const config = runtimeConfig();
    const dependencies = runtimeDependencies(
      notebookExport,
      [studioManifest(notebookExport, { mode: "baseline" })],
      renderer.handle,
    );

    const session = await mountZeroPythonRuntime(
      {
        presentation: config,
        root: runtimeRoot(),
        signal: new AbortController().signal,
        commitRuntimeInstance: vi.fn(),
      },
      config.runtime.data,
      dependencies,
    );

    expect(globalThis.marimoStudio.state?.inputs()).toEqual({ mode: "alternate" });
    expect(dependencies.setConnectionState).toHaveBeenLastCalledWith("ready");

    const revision = await session.beginRevision(new AbortController().signal);
    await revision.apply(config);
    await revision.commit();

    expect(globalThis.marimoStudio.state?.inputs()).toEqual({ mode: "alternate" });

    await session.dispose();
    globalThis.history.replaceState({}, "", "/");
  });

  it("keeps the prepared default when the initial query is unavailable", async () => {
    installMarimoStudioGlobal();
    globalThis.history.replaceState({}, "", "?mode=missing");
    const notebookExport = notebookExportFixture({
      inputs: [{ mode: "baseline" }, { mode: "alternate" }],
    });
    const renderer = rendererFixture();
    const config = runtimeConfig();
    const dependencies = runtimeDependencies(
      notebookExport,
      [studioManifest(notebookExport, { mode: "baseline" })],
      renderer.handle,
    );

    const session = await mountZeroPythonRuntime(
      {
        presentation: config,
        root: runtimeRoot(),
        signal: new AbortController().signal,
        commitRuntimeInstance: vi.fn(),
      },
      config.runtime.data,
      dependencies,
    );

    expect(globalThis.marimoStudio.state?.inputs()).toEqual({ mode: "baseline" });
    expect(dependencies.setConnectionState).toHaveBeenLastCalledWith("ready");

    await session.dispose();
    globalThis.history.replaceState({}, "", "/");
  });

  it("keeps the prepared default when the initial query is ambiguous", async () => {
    installMarimoStudioGlobal();
    globalThis.history.replaceState({}, "", "?value=1");
    const notebookExport = notebookExportFixture({ inputs: [{ value: "1" }, { value: 1 }] });
    const renderer = rendererFixture();
    const config = runtimeConfig();
    const dependencies = runtimeDependencies(
      notebookExport,
      [studioManifest(notebookExport, { value: "1" })],
      renderer.handle,
    );

    const session = await mountZeroPythonRuntime(
      {
        presentation: config,
        root: runtimeRoot(),
        signal: new AbortController().signal,
        commitRuntimeInstance: vi.fn(),
      },
      config.runtime.data,
      dependencies,
    );

    expect(globalThis.marimoStudio.state?.inputs()).toEqual({ value: "1" });
    expect(dependencies.setConnectionState).toHaveBeenLastCalledWith("ready");

    await session.dispose();
    globalThis.history.replaceState({}, "", "/");
  });

  it("reloads another runtime before parsing its adapter data", async () => {
    installMarimoStudioGlobal();
    const notebookExport = notebookExportFixture({ inputs: [{ mode: "baseline" }] });
    const renderer = rendererFixture();
    const config = runtimeConfig();
    const session = await mountZeroPythonRuntime(
      {
        presentation: config,
        root: runtimeRoot(),
        signal: new AbortController().signal,
        commitRuntimeInstance: vi.fn(),
      },
      config.runtime.data,
      runtimeDependencies(
        notebookExport,
        [studioManifest(notebookExport, { mode: "baseline" })],
        renderer.handle,
      ),
    );

    const revision = await session.beginRevision(new AbortController().signal);
    await expect(
      revision.apply({
        ...config,
        runtime: {
          descriptor: { ...ZERO_PYTHON_RUNTIME_DESCRIPTOR, id: "server" },
          instance: "server-runtime",
          data: { invalid: true },
        },
      }),
    ).resolves.toBe("reload");
    await revision.commit();
    expect(renderer.handle.update).not.toHaveBeenCalled();
    await session.dispose();
  });

  it("rejects an initial manifest from another runtime binding", async () => {
    installMarimoStudioGlobal();
    const stale = notebookExportFixture({
      identity: "2".repeat(64),
      inputs: [{ mode: "stale" }],
    });
    const renderer = rendererFixture();
    const config = runtimeConfig();

    await expect(
      mountZeroPythonRuntime(
        {
          presentation: config,
          root: runtimeRoot(),
          signal: new AbortController().signal,
          commitRuntimeInstance: vi.fn(),
        },
        config.runtime.data,
        runtimeDependencies(
          stale,
          [studioManifest(stale, stale.defaultState.inputs)],
          renderer.handle,
        ),
      ),
    ).rejects.toThrow(/runtime instance/);

    expect(renderer.handle.dispose).toHaveBeenCalledOnce();
  });

  it("restores publication, renderer, and state API across revision rollback", async () => {
    installMarimoStudioGlobal();
    const notebookExport = notebookExportFixture({
      inputs: [{ mode: "baseline" }, { mode: "alternate" }],
    });
    const renderer = rendererFixture();
    const config = runtimeConfig();
    const dependencies = runtimeDependencies(
      notebookExport,
      [
        studioManifest(notebookExport, { mode: "baseline" }),
        studioManifest(notebookExport, { mode: "alternate" }),
      ],
      renderer.handle,
    );
    const session = await mountZeroPythonRuntime(
      {
        presentation: config,
        root: runtimeRoot(),
        signal: new AbortController().signal,
        commitRuntimeInstance: vi.fn(),
      },
      config.runtime.data,
      dependencies,
    );
    const revision = await session.beginRevision(new AbortController().signal);
    await globalThis.marimoStudio.state?.update({ mode: "alternate" });
    const next = {
      ...config,
      revision: "revision-2",
      runtime: { ...config.runtime, instance: notebookExport.identity },
    };

    await revision.apply(next);
    expect(globalThis.marimoStudio.state?.inputs()).toEqual({ mode: "alternate" });
    expect(renderer.checkpoints).toHaveLength(1);
    await revision.rollback();

    expect(globalThis.marimoStudio.state?.inputs()).toEqual({ mode: "baseline" });
    expect(
      renderer.checkpoints.some((checkpoint) => checkpoint.restore.mock.calls.length > 0),
    ).toBe(true);
    await session.dispose();
  });

  it("restores the previous refresh anchor after a wrong-instance revision", async () => {
    vi.useFakeTimers();
    installMarimoStudioGlobal();
    const first = notebookExportFixture({
      identity: "1".repeat(64),
      inputs: [{ mode: "baseline" }, { mode: "alternate" }],
    });
    const wrong = notebookExportFixture({
      identity: "3".repeat(64),
      inputs: [{ mode: "wrong" }],
    });
    const pollingManifest = (mode: "baseline" | "alternate") => {
      const manifest = studioManifest(first, { mode });
      return {
        ...manifest,
        prepared: { ...manifest.prepared, refresh_interval_ms: 250 },
      };
    };
    const renderer = rendererFixture();
    const config = runtimeConfig();
    const dependencies = runtimeDependencies(
      first,
      [
        pollingManifest("baseline"),
        studioManifest(wrong, wrong.defaultState.inputs),
        pollingManifest("alternate"),
      ],
      renderer.handle,
    );
    const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    let session: Awaited<ReturnType<typeof mountZeroPythonRuntime>> | undefined;
    try {
      session = await mountZeroPythonRuntime(
        {
          presentation: config,
          root: runtimeRoot(),
          signal: new AbortController().signal,
          commitRuntimeInstance: vi.fn(),
        },
        config.runtime.data,
        dependencies,
      );
      const revision = await session.beginRevision(new AbortController().signal);

      await expect(
        revision.apply({
          ...config,
          revision: "revision-2",
          runtime: { ...config.runtime, instance: "2".repeat(64) },
        }),
      ).rejects.toThrow(/runtime instance/u);
      await revision.rollback();
      await vi.advanceTimersByTimeAsync(250);

      expect(dependencies.fetch).toHaveBeenCalledTimes(3);
      expect(globalThis.marimoStudio.state?.inputs()).toEqual({ mode: "alternate" });
      expect(renderer.snapshots).toHaveLength(2);
      expect(warning).not.toHaveBeenCalled();
    } finally {
      await session?.dispose();
      warning.mockRestore();
      vi.useRealTimers();
    }
  });

  it("commits a background publication instance with its rendered state", async () => {
    vi.useFakeTimers();
    installMarimoStudioGlobal();
    const first = notebookExportFixture({
      identity: "1".repeat(64),
      inputs: [{ mode: "baseline" }],
    });
    const second = notebookExportFixture({
      identity: "2".repeat(64),
      inputs: [{ mode: "rotated" }],
      controlBindings: { rotated: { input: "mode", path: [] } },
    });
    const initialManifest = studioManifest(first, first.defaultState.inputs);
    const renderer = rendererFixture();
    const config = runtimeConfig();
    let committedConfig = config;
    const commitRuntimeInstance = vi.fn((instance: string) => {
      committedConfig = {
        ...committedConfig,
        runtime: { ...committedConfig.runtime, instance },
      };
    });
    const dependencies = {
      ...runtimeDependencies(
        first,
        [
          {
            ...initialManifest,
            prepared: { ...initialManifest.prepared, refresh_interval_ms: 250 },
          },
          studioManifest(second, second.defaultState.inputs),
        ],
        renderer.handle,
      ),
      openExport: vi.fn(async (base: string | URL) =>
        new URL(base).href === second.base.href ? second : first,
      ),
    };
    let session: Awaited<ReturnType<typeof mountZeroPythonRuntime>> | undefined;
    try {
      session = await mountZeroPythonRuntime(
        {
          presentation: config,
          root: runtimeRoot(),
          signal: new AbortController().signal,
          commitRuntimeInstance,
        },
        config.runtime.data,
        dependencies,
      );
      await vi.advanceTimersByTimeAsync(250);

      expect(renderer.snapshots).toHaveLength(2);
      expect(renderer.handle.updateControlBindings).toHaveBeenLastCalledWith(
        second.controlBindings,
      );
      expect(globalThis.marimoStudio.state?.inputs()).toEqual({ mode: "rotated" });
      expect(committedConfig.runtime.instance).toBe(second.identity);
      expect(commitRuntimeInstance).toHaveBeenLastCalledWith(second.identity);
    } finally {
      await session?.dispose();
      vi.useRealTimers();
    }
  });

  it("preserves retained inputs when a revision removes another input", async () => {
    installMarimoStudioGlobal();
    const first = notebookExportFixture({
      identity: "1".repeat(64),
      inputs: [{ retained: "selected", removed: "old" }],
    });
    const second = notebookExportFixture({
      identity: "2".repeat(64),
      inputs: [{ retained: "selected", added: "new" }],
    });
    const renderer = rendererFixture();
    const config = runtimeConfig();
    const dependencies = {
      ...runtimeDependencies(
        first,
        [
          studioManifest(first, first.defaultState.inputs),
          studioManifest(second, second.defaultState.inputs),
        ],
        renderer.handle,
      ),
      openExport: vi.fn(async (base: string | URL) =>
        new URL(base).href === second.base.href ? second : first,
      ),
    };
    const session = await mountZeroPythonRuntime(
      {
        presentation: config,
        root: runtimeRoot(),
        signal: new AbortController().signal,
        commitRuntimeInstance: vi.fn(),
      },
      config.runtime.data,
      dependencies,
    );
    const revision = await session.beginRevision(new AbortController().signal);

    await expect(
      revision.apply({
        ...config,
        revision: "revision-2",
        runtime: { ...config.runtime, instance: second.identity },
      }),
    ).resolves.toBe("applied");
    expect(globalThis.marimoStudio.state?.inputs()).toEqual({
      retained: "selected",
      added: "new",
    });

    await revision.commit();
    await session.dispose();
  });

  it("uses the new default when retained revision inputs are unavailable", async () => {
    installMarimoStudioGlobal();
    const first = notebookExportFixture({
      identity: "1".repeat(64),
      inputs: [{ retained: "old", removed: true }],
    });
    const second = notebookExportFixture({
      identity: "2".repeat(64),
      inputs: [{ retained: "new", added: true }],
    });
    const renderer = rendererFixture();
    const config = runtimeConfig();
    const dependencies = {
      ...runtimeDependencies(
        first,
        [
          studioManifest(first, first.defaultState.inputs),
          studioManifest(second, second.defaultState.inputs),
        ],
        renderer.handle,
      ),
      openExport: vi.fn(async (base: string | URL) =>
        new URL(base).href === second.base.href ? second : first,
      ),
    };
    const session = await mountZeroPythonRuntime(
      {
        presentation: config,
        root: runtimeRoot(),
        signal: new AbortController().signal,
        commitRuntimeInstance: vi.fn(),
      },
      config.runtime.data,
      dependencies,
    );
    const revision = await session.beginRevision(new AbortController().signal);

    await expect(
      revision.apply({
        ...config,
        revision: "revision-2",
        runtime: { ...config.runtime, instance: second.identity },
      }),
    ).resolves.toBe("applied");
    expect(globalThis.marimoStudio.state?.inputs()).toEqual({ retained: "new", added: true });

    await revision.commit();
    await session.dispose();
  });

  it("publishes startup diagnostics and releases renderer ownership on failure", async () => {
    installMarimoStudioGlobal();
    const notebookExport = notebookExportFixture({ inputs: [{ mode: "baseline" }] });
    const renderer = rendererFixture();
    const config = runtimeConfig();
    const dependencies = {
      ...runtimeDependencies(
        notebookExport,
        [studioManifest(notebookExport, { mode: "baseline" })],
        renderer.handle,
      ),
      fetch: vi.fn(async () => new Response(null, { status: 409 })),
    };

    await expect(
      mountZeroPythonRuntime(
        {
          presentation: config,
          root: runtimeRoot(),
          signal: new AbortController().signal,
          commitRuntimeInstance: vi.fn(),
        },
        config.runtime.data,
        dependencies,
      ),
    ).rejects.toThrow(/failed with 409/);

    expect(dependencies.setConnectionState).toHaveBeenCalledWith(
      "error",
      expect.objectContaining({ code: "manifest_read_failed" }),
    );
    expect(renderer.handle.dispose).toHaveBeenCalledOnce();
  });
});
