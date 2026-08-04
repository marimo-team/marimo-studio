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
  it("resolves one declared runtime", () => {
    const registry = createRuntimeRegistry([runtime("server"), runtime("wasm")]);

    expect(registry.get("wasm").id).toBe("wasm");
  });

  it("rejects duplicate runtime IDs", () => {
    expect(() => createRuntimeRegistry([runtime("server"), runtime("server")])).toThrow(
      'Duplicate runtime ID "server"',
    );
  });
});
