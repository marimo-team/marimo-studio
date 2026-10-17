import { createRuntimeRegistry } from "@marimo-studio/runtime";
import { afterEach, expect, test, vi } from "vite-plus/test";

import { startStaticPresentation } from "../src/static.ts";
import { runtimeConfig } from "./runtime-fixtures.ts";

afterEach(() => {
  window.dispatchEvent(new Event("pagehide"));
  document.body.replaceChildren();
  vi.unstubAllGlobals();
});

test("a static export shows a render that reads no notebook results", async () => {
  globalThis.__MARIMO_MOUNT_CONFIG__ = {
    supportUrl: "http://localhost:3000/_marimo-studio/views/dashboard",
    revision: "presentation-revision",
    runtime: "zero-python",
    version: "0.23.9",
    runtimeExplicit: false,
    replay: false,
  };
  const config = runtimeConfig({
    runtime: { id: "zero-python", instance: "export", data: {}, urls: {} },
    mode: "run",
  });
  const bundle = "c".repeat(64);
  vi.stubGlobal("fetch", async (input: string | URL) => {
    const url = input.toString();
    if (url.includes("/config")) {
      return new Response(JSON.stringify(config));
    }
    if (url === `${config.supportUrl}/renders/index.json`) {
      return new Response(
        JSON.stringify({
          schema: 2,
          bundles: {
            [bundle]: {
              files: [{ path: "card.svg", mediaType: "image/svg+xml", sha256: bundle, size: 9 }],
              main: "card.svg",
              preview: null,
              regions: [],
            },
          },
          states: { baseline: { "card.svg": { bundle, warnings: [], absent: [] } } },
        }),
      );
    }
    return new Response(null, { status: 404 });
  });
  HTMLImageElement.prototype.decode = () => Promise.resolve();
  document.body.innerHTML = `
    <main id="app-shell"><marimo-output render="card.svg"></marimo-output></main>
    <div id="marimo-runtime-root" hidden></div>
  `;

  startStaticPresentation(createRuntimeRegistry([]));

  const host = document.querySelector<HTMLElement>("marimo-output")!;
  await vi.waitFor(() => expect(host.dataset.state).toBe("ready"));
  expect(host.shadowRoot?.querySelector("img")?.getAttribute("src")).toBe(
    `${config.supportUrl}/renders/${bundle}/card.svg`,
  );
  await vi.waitFor(() => expect(document.documentElement.dataset.marimoStudioState).toBe("ready"));
});
