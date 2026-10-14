import { createRuntimeRegistry } from "@marimo-studio/runtime";
import { afterEach, expect, test, vi } from "vite-plus/test";

import { startStaticPresentation } from "../src/static.ts";
import { runtimeConfig } from "./runtime-fixtures.ts";

afterEach(() => {
  window.dispatchEvent(new Event("pagehide"));
  document.body.replaceChildren();
  vi.unstubAllGlobals();
});

test("loads a static document with an empty projection catalog", async () => {
  globalThis.__MARIMO_MOUNT_CONFIG__ = {
    supportUrl: "http://localhost:3000/_marimo-studio/views/dashboard",
    revision: "presentation-revision",
    runtime: "zero-python",
    version: "0.23.9",
    runtimeExplicit: false,
    replay: false,
  };
  const config = runtimeConfig({
    runtime: { id: "zero-python", instance: "document", data: {}, urls: {} },
  });
  vi.stubGlobal("fetch", async (input: string | URL) => {
    if (input.toString().includes("/config")) {
      return new Response(JSON.stringify(config));
    }
    return new Response('<svg xmlns="http://www.w3.org/2000/svg"></svg>', {
      headers: { "Content-Type": "image/svg+xml" },
    });
  });
  vi.stubGlobal("marimoStudio", {});
  URL.createObjectURL = () => "blob:document";
  URL.revokeObjectURL = () => {};
  HTMLImageElement.prototype.decode = () => Promise.resolve();
  document.body.innerHTML = `
    <main id="app-shell"><marimo-document src="card.svg" type="image/svg+xml" render></marimo-document></main>
    <div id="marimo-runtime-root" hidden></div>
  `;

  startStaticPresentation(createRuntimeRegistry([]));

  await vi.waitFor(() => expect(window.__MARIMO_STUDIO_RUNTIME_STATE__).toBe("mounted"));
  await vi.waitFor(() =>
    expect(document.querySelector<HTMLElement>("marimo-document")?.dataset.state).toBe("ready"),
  );
  await vi.waitFor(() => expect(document.documentElement.dataset.marimoStudioState).toBe("ready"));
});
