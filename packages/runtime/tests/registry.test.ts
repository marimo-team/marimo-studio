import { describe, expect, it } from "vite-plus/test";

import {
  createRuntimeRegistry,
  definePresentationRuntime,
  type PresentationRuntime,
} from "../src/index";

const runtime = (id: string): PresentationRuntime =>
  definePresentationRuntime({
    id,
    mount: async () => ({
      id,
      update: () => "applied",
      updateQuery: async () => {},
      dispose: () => {},
    }),
  });

describe("runtime registry", () => {
  it("exposes one immutable catalog of declared runtimes", () => {
    const registry = createRuntimeRegistry([runtime("server"), runtime("wasm")]);

    expect(registry.runtimes.map(({ id }) => id)).toEqual(["server", "wasm"]);
    expect(registry.has("wasm")).toBe(true);
    expect(registry.has("missing")).toBe(false);
    expect(registry.get("wasm").id).toBe("wasm");
    expect(Object.isFrozen(registry)).toBe(true);
    expect(Object.isFrozen(registry.runtimes)).toBe(true);
  });

  it("rejects invalid declarations and unknown lookups", () => {
    expect(() => createRuntimeRegistry([runtime("WASM")])).toThrow('Invalid runtime ID "WASM"');
    expect(() => createRuntimeRegistry([runtime("server"), runtime("server")])).toThrow(
      'Duplicate runtime ID "server"',
    );
    expect(() => createRuntimeRegistry([runtime("server")]).get("wasm")).toThrow(
      'Unknown runtime "wasm"',
    );
  });
});
