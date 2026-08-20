import { describe, expect, it } from "vite-plus/test";

import {
  createRuntimeRegistry,
  definePresentationRuntime,
  type PresentationRuntime,
} from "../src/index";

const descriptor = (id: string) => ({
  id,
  label: id,
  description: `Runs ${id}`,
  execution: "prepared" as const,
  projections: { cell: true, output: true, value: true },
  controls: "none" as const,
  query: "none" as const,
  preparation: "on-select" as const,
  session: "none" as const,
});

const runtime = (id: string): PresentationRuntime =>
  definePresentationRuntime({
    descriptor: descriptor(id),
    mount: async () => ({
      id,
      beginRevision: async () => ({
        apply: async () => "applied" as const,
        commit: () => {},
        rollback: () => {},
      }),
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

  it("rejects server descriptors that diverge from browser composition", () => {
    const registry = createRuntimeRegistry([runtime("server")]);

    expect(() => registry.resolve({ ...descriptor("server"), controls: "peer" })).toThrow(
      'Runtime descriptor "server" does not match the registered runtime',
    );
  });
});
