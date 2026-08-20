import { describe, expect, it } from "vite-plus/test";

import type { BrowserBundle, BrowserChunk } from "../entry-closures.ts";

import { buildEntryClosures, validateWrittenEntryClosures } from "../entry-closures.ts";

interface ChunkOptions {
  readonly imports?: string[];
  readonly dynamicImports?: string[];
  readonly modules?: string[];
  readonly styles?: string[];
  readonly assets?: string[];
  readonly referencedFiles?: string[];
  readonly renderedLength?: number;
}

const chunk = (name: string, options: ChunkOptions = {}): BrowserChunk => ({
  type: "chunk",
  dynamicImports: options.dynamicImports ?? [],
  fileName: `${name}.js`,
  imports: options.imports ?? [],
  isEntry: name === "runtime" || name === "zero-python",
  modules: Object.fromEntries(
    (options.modules ?? [`/src/${name}.ts`]).map((moduleId) => [
      moduleId,
      options.renderedLength === undefined ? {} : { renderedLength: options.renderedLength },
    ]),
  ),
  name,
  referencedFiles: options.referencedFiles ?? [],
  viteMetadata: {
    importedAssets: new Set(options.assets ?? []),
    importedCss: new Set(options.styles ?? []),
  },
});

const bundle = (): BrowserBundle => ({
  "runtime.js": chunk("runtime", { imports: ["shared.js"] }),
  "zero-python.js": chunk("zero-python", {
    imports: ["shared.js", "prepared.js"],
    styles: ["zero-python.css"],
  }),
  "shared.js": chunk("shared", { assets: ["assets/icon.svg"] }),
  "prepared.js": chunk("prepared"),
  "assets/icon.svg": { type: "asset" },
  "zero-python.css": { type: "asset" },
});

describe("browser entry closures", () => {
  it("emits complete safe closures for runtime and zero-Python entries", () => {
    expect(buildEntryClosures(bundle())).toEqual({
      schema: 1,
      entries: {
        runtime: {
          script: "runtime.js",
          styles: [],
          assets: ["assets/icon.svg", "shared.js"],
        },
        "zero-python": {
          script: "zero-python.js",
          styles: ["zero-python.css"],
          assets: ["assets/icon.svg", "prepared.js", "shared.js"],
        },
      },
    });
  });

  it("rejects server, WASM, worker, and session modules from zero-Python", () => {
    const invalid = bundle();
    invalid["prepared.js"] = chunk("prepared", {
      modules: ["/packages/presentation/src/runtime/wasm.ts"],
    });

    expect(() => buildEntryClosures(invalid)).toThrow(/forbidden execution modules/);
  });

  it("keeps the export reader out of the normal runtime closure", () => {
    const invalid = bundle();
    invalid["runtime.js"] = chunk("runtime", { imports: ["zero-adapter.js"] });
    invalid["zero-adapter.js"] = chunk("zero-adapter", {
      modules: ["/workspace/marimo-export/packages/browser/dist/index.mjs"],
    });

    expect(() => buildEntryClosures(invalid)).toThrow(/closure imports Zero-Python/);
  });

  it("keeps the app-owned prepared adapter out of the normal runtime closure", () => {
    const invalid = bundle();
    invalid["runtime.js"] = chunk("runtime", { imports: ["zero-adapter.js"] });
    invalid["zero-adapter.js"] = chunk("zero-adapter", {
      modules: ["/workspace/apps/browser/src/zero-python/controller.ts"],
    });

    expect(() => buildEntryClosures(invalid)).toThrow(/closure imports Zero-Python/);
  });

  it("excludes the lazy Zero-Python subtree from the runtime deployment closure", () => {
    const output = bundle();
    output["runtime.js"] = chunk("runtime", {
      dynamicImports: ["slides.js", "zero-loader.js"],
      imports: ["shared.js"],
    });
    output["slides.js"] = chunk("slides", {
      modules: ["/workspace/packages/presentation/src/runtime/slides.ts"],
      styles: ["slides.css"],
    });
    output["zero-loader.js"] = chunk("zero-loader", {
      imports: ["prepared.js"],
      modules: ["/workspace/apps/browser/src/zero-python/mount.ts"],
    });
    output["prepared.js"] = chunk("prepared", {
      modules: ["/workspace/marimo-export/packages/browser/dist/index.mjs"],
    });
    output["slides.css"] = { type: "asset" };

    expect(buildEntryClosures(output).entries.runtime).toEqual({
      script: "runtime.js",
      styles: ["slides.css"],
      assets: ["assets/icon.svg", "shared.js", "slides.js"],
    });
  });

  it("rejects Zero-Python content that remains in the retained runtime closure", () => {
    const invalid = bundle();
    invalid["runtime.js"] = chunk("runtime", {
      dynamicImports: ["bridge.js"],
      imports: ["shared.js"],
    });
    invalid["bridge.js"] = chunk("bridge", {
      imports: ["zero-adapter.js"],
      modules: ["/workspace/packages/presentation/src/runtime/bridge.ts"],
    });
    invalid["zero-adapter.js"] = chunk("zero-adapter", {
      modules: ["/workspace/apps/browser/src/zero-python/controller.ts"],
    });

    expect(() => buildEntryClosures(invalid)).toThrow(/closure imports Zero-Python/);
  });

  it("allows the runtime-neutral portable JSON package", () => {
    const output = bundle();
    output["shared.js"] = chunk("shared", {
      modules: [
        "/workspace/marimo-export/packages/portable-json/dist/index.mjs",
        "/workspace/marimo-export/packages/portable-json/dist/zod.mjs",
      ],
    });

    expect(() => buildEntryClosures(output)).not.toThrow();
  });

  it("rejects unsafe generated paths", () => {
    const invalid = bundle();
    invalid["zero-python.js"] = {
      ...chunk("zero-python", { imports: ["../outside.js"] }),
      imports: ["../outside.js"],
    };
    invalid["../outside.js"] = chunk("outside");

    expect(() => buildEntryClosures(invalid)).toThrow(/unsafe path/);
  });

  it("keeps extracted CSS and omits its non-written facade chunk", () => {
    const output = bundle();
    output["runtime.js"] = chunk("runtime", {
      dynamicImports: ["slides.js"],
      imports: ["shared.js"],
    });
    output["slides.js"] = chunk("slides", {
      modules: ["/src/slides.css"],
      renderedLength: 0,
      styles: ["slides.css"],
    });
    output["slides.css"] = { type: "asset" };

    expect(buildEntryClosures(output).entries.runtime).toEqual({
      script: "runtime.js",
      styles: ["slides.css"],
      assets: ["assets/icon.svg", "shared.js"],
    });
  });

  it("rejects a missing imported chunk", () => {
    const output = bundle();
    output["runtime.js"] = chunk("runtime", { imports: ["missing.js"] });

    expect(() => buildEntryClosures(output)).toThrow(/runtime\.js.*import.*missing\.js/u);
  });

  it("rejects a missing imported stylesheet", () => {
    const output = bundle();
    output["shared.js"] = chunk("shared", { styles: ["missing.css"] });

    expect(() => buildEntryClosures(output)).toThrow(/shared\.js.*CSS.*missing\.css/u);
  });

  it("rejects a missing imported asset", () => {
    const output = bundle();
    output["shared.js"] = chunk("shared", { assets: ["assets/missing.svg"] });

    expect(() => buildEntryClosures(output)).toThrow(/shared\.js.*asset.*missing\.svg/u);
  });

  it("rejects a missing referenced file", () => {
    const output = bundle();
    output["shared.js"] = chunk("shared", { referencedFiles: ["chunks/missing.js"] });

    expect(() => buildEntryClosures(output)).toThrow(/shared\.js.*referenced file.*missing\.js/u);
  });

  it("rejects a declared closure member missing after write", () => {
    const closures = buildEntryClosures(bundle());
    const emitted = new Set([
      "runtime.js",
      "zero-python.js",
      "prepared.js",
      "assets/icon.svg",
      "zero-python.css",
    ]);

    expect(() => validateWrittenEntryClosures(closures, emitted)).toThrow(
      /runtime.*asset.*shared\.js.*not written/u,
    );
  });
});
