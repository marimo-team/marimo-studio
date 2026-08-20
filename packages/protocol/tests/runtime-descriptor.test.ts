import { expect, test } from "vite-plus/test";

import { parseRuntimeAvailability, runtimeDescriptorSchema } from "../src/runtime-descriptor.ts";

const descriptor = {
  id: "server",
  label: "Server",
  description: "Uses the notebook kernel",
  execution: "kernel",
  projections: { cell: true, output: true, value: true },
  controls: "peer",
  query: "reactive",
  preparation: "primary",
  session: "shared",
};

test("runtime descriptors validate every execution capability", () => {
  expect(runtimeDescriptorSchema.parse(descriptor)).toEqual(descriptor);
  expect(() =>
    runtimeDescriptorSchema.parse({
      ...descriptor,
      projections: { cell: true, output: true },
    }),
  ).toThrow();
  expect(() => runtimeDescriptorSchema.parse({ ...descriptor, preparation: "eager" })).toThrow();
});

test("runtime descriptors reject undeclared fields", () => {
  expect(() => runtimeDescriptorSchema.parse({ ...descriptor, transport: "http" })).toThrow();
  expect(() =>
    runtimeDescriptorSchema.parse({
      ...descriptor,
      projections: { ...descriptor.projections, table: true },
    }),
  ).toThrow();
});

test("runtime availability binds descriptors to source and presentation revisions", () => {
  const availability = {
    schema: 1 as const,
    view: "dashboard",
    runtimes: ["server", "zero-python"],
    revision: "presentation-revision",
    sources: {
      "index.html": "sha256:index",
      "app.css": "sha256:style",
    },
  };

  expect(parseRuntimeAvailability(availability)).toEqual(availability);
  expect(() =>
    parseRuntimeAvailability({
      ...availability,
      sources: { ...availability.sources, "index.html": "" },
    }),
  ).toThrow();
});
