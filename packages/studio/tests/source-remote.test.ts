import { expect, it, vi } from "vite-plus/test";

import type { RevisionConflict } from "../src/features/source-editor/remote.ts";

import { createSourceRemote } from "../src/features/source-editor/remote.ts";
import { unbuiltView } from "./fixtures.ts";

it("reads nested provider paths through encoded source URLs", async () => {
  const requests: string[] = [];
  vi.stubGlobal("fetch", async (input: string | URL | Request) => {
    const url = input instanceof Request ? input.url : input.toString();
    requests.push(url);
    return new Response("content", {
      headers: {
        ETag: '"sha256:source"',
        "Marimo-Studio-Catalog-Generation": "a".repeat(64),
        "Marimo-Studio-View-Generation": "b".repeat(64),
      },
    });
  });
  const remote = createSourceRemote(
    (view) => `http://localhost/_marimo-studio/views/${view}`,
    "token",
  );

  const source = await remote.read("react", "src/cards/Metric #1.tsx");

  expect(new URL(requests[0]).pathname).toBe(
    "/_marimo-studio/views/react/source/src/cards/Metric%20%231.tsx",
  );
  expect(source.catalogGeneration).toBe("a".repeat(64));
  expect(source.viewGeneration).toBe("b".repeat(64));
});

it("parses provider project catalogs from the view support endpoint", async () => {
  const manifestDiagnostic = {
    code: "provider-options-invalid",
    severity: "error" as const,
    message: "The provider options are invalid.",
    hint: "Repair view.toml.",
    source: { path: "view.toml", line: 1, column: 1 },
  };
  vi.stubGlobal("fetch", async () =>
    Response.json({
      schema: 1,
      catalog_generation: "a".repeat(64),
      view_generation: "b".repeat(64),
      view: "svelte",
      provider: "marimo-studio/svelte",
      provider_options: {},
      documents: [{ path: "src/App.svelte", language: "svelte", access: "edit", label: null }],
      mounts: [],
      diagnostics: [manifestDiagnostic],
      build: { ...unbuiltView, phase: "failed", diagnostics: [manifestDiagnostic] },
      artifact: null,
    }),
  );
  const remote = createSourceRemote(
    (view) => `http://localhost/_marimo-studio/views/${view}`,
    "token",
  );

  const project = await remote.project("svelte");

  expect(project.documents).toEqual([
    { path: "src/App.svelte", language: "svelte", access: "edit", label: null },
  ]);
  expect(project.diagnostics[0]?.source?.path).toBe("view.toml");
  expect(project.build.diagnostics[0]?.source?.path).toBe("view.toml");
  expect(Object.getPrototypeOf(project.provider_options)).toBeNull();
});

it.each(["project", "source"] as const)(
  "drains and surfaces a structured %s read failure",
  async (operation) => {
    const failed = Response.json(
      {
        error: "configuration-error",
        message: "Repair the invalid view manifest.",
      },
      { status: 500 },
    );
    vi.stubGlobal("fetch", async () => failed);
    const remote = createSourceRemote(
      (view) => `http://localhost/_marimo-studio/views/${view}`,
      "token",
    );

    const read =
      operation === "project"
        ? remote.project("dashboard")
        : remote.read("dashboard", "src/index.html");

    await expect(read).rejects.toThrow("Repair the invalid view manifest.");
    expect(failed.bodyUsed).toBe(true);
  },
);

it("preserves external recovery metadata from a conditional source write", async () => {
  vi.stubGlobal("fetch", async (_input: RequestInfo | URL, init?: RequestInit) => {
    expect(new Headers(init?.headers).get("Marimo-Studio-Catalog-Generation")).toBe("a".repeat(64));
    expect(new Headers(init?.headers).get("Marimo-Studio-View-Generation")).toBe("b".repeat(64));
    return Response.json(
      {
        error: "source-conflict",
        message: "src/App.tsx changed on disk.",
        revision: "sha256:disk",
        external_recovery: "/workspace/.src-App.tsx.external-recovery",
      },
      { status: 412 },
    );
  });
  const remote = createSourceRemote(
    (view) => `http://localhost/_marimo-studio/views/${view}`,
    "token",
  );

  const write = remote.write(
    "react",
    "src/App.tsx",
    "local",
    "sha256:loaded",
    "a".repeat(64),
    "b".repeat(64),
  );

  await expect(write).rejects.toEqual(
    expect.objectContaining<Partial<RevisionConflict>>({
      revision: "sha256:disk",
      externalRecovery: "/workspace/.src-App.tsx.external-recovery",
    }),
  );
});
