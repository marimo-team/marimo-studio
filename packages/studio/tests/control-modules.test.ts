import { expect, it, vi } from "vite-plus/test";
import { z } from "zod";

import type {
  ControlEndpoint,
  ControlUpdate,
  EndpointControlBinding,
} from "../src/features/preview/control-types.ts";

import { QuarantinedControlBuffer } from "../src/features/preview/control-buffer.ts";
import {
  createControlTranslation,
  sameControlBindings,
} from "../src/features/preview/control-translation.ts";
import { ControlWriter } from "../src/features/preview/control-writer.ts";

it("coalesces one stalled control drain to the latest value", async () => {
  let release = () => {};
  const stalled = new Promise<void>((resolve) => {
    release = resolve;
  });
  const applied: (readonly ControlUpdate[])[] = [];
  const endpoint: ControlEndpoint = {
    snapshot: () => [],
    subscribe: () => () => {},
    apply: vi.fn(async (updates) => {
      applied.push(updates);
      if (applied.length === 1) {
        await stalled;
      }
    }),
    dispose: () => {},
  };
  const writer = new ControlWriter(endpoint);
  const first = writer.write([{ objectId: "scale", value: 1 }]);
  const intermediate = writer.write([{ objectId: "scale", value: 2 }]);
  const latest = writer.write([{ objectId: "scale", value: 3 }]);

  expect(intermediate).toBe(latest);
  release();
  await Promise.all([first, intermediate, latest]);
  expect(applied).toEqual([[{ objectId: "scale", value: 1 }], [{ objectId: "scale", value: 3 }]]);
});

it("reapplies a newer direct observation after an older apply settles", async () => {
  let release = () => {};
  const stalled = new Promise<void>((resolve) => {
    release = resolve;
  });
  const applied: (readonly ControlUpdate[])[] = [];
  const endpoint: ControlEndpoint = {
    snapshot: () => [{ objectId: "scale", value: 0 }],
    subscribe: () => () => {},
    apply: vi.fn(async (updates) => {
      applied.push(updates);
      await stalled;
    }),
    dispose: () => {},
  };
  const writer = new ControlWriter(endpoint);
  const applying = writer.write([{ objectId: "scale", value: 1 }]);
  writer.observe({ objectId: "scale", value: 2, origin: "input" });
  release();
  await applying;

  await writer.write([{ objectId: "scale", value: 2 }]);

  expect(applied).toEqual([[{ objectId: "scale", value: 1 }], [{ objectId: "scale", value: 2 }]]);
});

it("keeps a pending peer update after a late registration echo", async () => {
  let release = () => {};
  const stalled = new Promise<void>((resolve) => {
    release = resolve;
  });
  const applied: (readonly ControlUpdate[])[] = [];
  const endpoint: ControlEndpoint = {
    snapshot: () => [{ objectId: "scale", value: 0 }],
    subscribe: () => () => {},
    apply: vi.fn(async (updates) => {
      applied.push(updates);
      if (applied.length === 1) {
        await stalled;
      }
    }),
    dispose: () => {},
  };
  const writer = new ControlWriter(endpoint);
  const first = writer.write([{ objectId: "scale", value: 1 }]);
  const pending = writer.write([{ objectId: "scale", value: 2 }]);
  writer.observe({ objectId: "scale", value: 1, origin: "registration" });
  release();

  await Promise.all([first, pending]);
  await writer.write([{ objectId: "scale", value: 2 }]);
  await writer.write([{ objectId: "scale", value: 1 }]);

  expect(applied).toEqual([
    [{ objectId: "scale", value: 1 }],
    [{ objectId: "scale", value: 2 }],
    [{ objectId: "scale", value: 1 }],
  ]);
});

it("lets direct input supersede a newer pending peer update", async () => {
  let release = () => {};
  const stalled = new Promise<void>((resolve) => {
    release = resolve;
  });
  const applied: (readonly ControlUpdate[])[] = [];
  const endpoint: ControlEndpoint = {
    snapshot: () => [{ objectId: "scale", value: 0 }],
    subscribe: () => () => {},
    apply: vi.fn(async (updates) => {
      applied.push(updates);
      await stalled;
    }),
    dispose: () => {},
  };
  const writer = new ControlWriter(endpoint);
  const first = writer.write([{ objectId: "scale", value: 1 }]);
  const pending = writer.write([{ objectId: "scale", value: 3 }]);
  writer.observe({ objectId: "scale", value: 1, origin: "input" });
  release();

  await Promise.all([first, pending]);
  await writer.write([{ objectId: "scale", value: 1 }]);

  expect(applied).toEqual([[{ objectId: "scale", value: 1 }]]);
});

it("reapplies an inflight value after a stale registration remount", async () => {
  let release = () => {};
  const stalled = new Promise<void>((resolve) => {
    release = resolve;
  });
  const applied: (readonly ControlUpdate[])[] = [];
  const endpoint: ControlEndpoint = {
    snapshot: () => [{ objectId: "scale", value: 1 }],
    subscribe: () => () => {},
    apply: vi.fn(async (updates) => {
      applied.push(updates);
      if (applied.length === 1) {
        await stalled;
      }
    }),
    dispose: () => {},
  };
  const writer = new ControlWriter(endpoint);
  const applying = writer.write([{ objectId: "scale", value: 3 }]);
  expect(writer.observe({ objectId: "scale", value: 1, origin: "registration" })).toBe(false);
  release();

  await applying;
  await writer.write([{ objectId: "scale", value: 3 }]);

  expect(applied).toEqual([[{ objectId: "scale", value: 3 }], [{ objectId: "scale", value: 3 }]]);
});

it("retries a rolled-back local update until the kernel converges", async () => {
  let browserValue = 1;
  let kernelValue = 1;
  let failSend = true;
  const endpoint: ControlEndpoint = {
    snapshot: () => [{ objectId: "scale", value: browserValue }],
    subscribe: () => () => {},
    apply: async ([update]) => {
      const value = z.number().parse(update?.value);
      const previous = browserValue;
      browserValue = value;
      if (failSend) {
        failSend = false;
        browserValue = previous;
        throw new Error("send failed");
      }
      kernelValue = value;
    },
    dispose: () => {},
  };
  const writer = new ControlWriter(endpoint);

  await expect(writer.write([{ objectId: "scale", value: 2 }])).rejects.toThrow("send failed");
  expect(browserValue).toBe(1);
  expect(kernelValue).toBe(1);

  await writer.write([{ objectId: "scale", value: 2 }]);

  expect(browserValue).toBe(2);
  expect(kernelValue).toBe(2);
});

it("requires an authoritative snapshot after the quarantine buffer fills", () => {
  const buffer = new QuarantinedControlBuffer();
  for (let index = 0; index < 257; index += 1) {
    buffer.add("editor", { objectId: `control-${index}`, value: index, origin: "input" }, index);
  }

  expect(buffer.snapshotSources()).toEqual(["editor"]);
  expect(buffer.takeOldest()).toBeUndefined();
  buffer.snapshotCaptured("editor");
  buffer.add("editor", { objectId: "scale", value: 3, origin: "input" }, 3);
  expect(buffer.takeOldest()).toMatchObject({
    source: "editor",
    update: { objectId: "scale", value: 3 },
  });
});

it("keeps direct input when a registration echo arrives later", () => {
  const buffer = new QuarantinedControlBuffer();
  buffer.add("preview", { objectId: "scale", value: 3, origin: "input" }, 3);
  buffer.add("preview", { objectId: "scale", value: 1, origin: "registration" }, 1);

  expect(buffer.takeOldest()).toMatchObject({
    source: "preview",
    update: { objectId: "scale", value: 3, origin: "input" },
  });
});

it("counts captured semantic bindings against the quarantine byte cap", () => {
  const buffer = new QuarantinedControlBuffer();
  const binding: EndpointControlBinding = {
    input: "filters",
    path: Array.from({ length: 256 }, () => ({ kind: "key", value: "x".repeat(1_024) })),
  };
  for (let index = 0; index < 80; index += 1) {
    buffer.add(
      "editor",
      { objectId: `control-${index}`, value: index, origin: "input" },
      index,
      binding,
    );
  }

  expect(buffer.snapshotSources()).toEqual(["editor"]);
  expect(buffer.takeOldest()).toBeUndefined();
});

it("translates reserved object IDs through structural control bindings", () => {
  const editorBindings = Object.fromEntries([
    ["__proto__", { input: "filters", path: [{ kind: "key" as const, value: "region" }] }],
  ]);
  const previewBindings = {
    prepared: { input: "filters", path: [{ kind: "key" as const, value: "region" }] },
  };
  const translation = createControlTranslation(
    { bindings: editorBindings },
    { bindings: previewBindings },
  );

  expect(translation.editor({ objectId: "__proto__", value: "apac" })).toEqual([
    { objectId: "prepared", value: "apac" },
  ]);
});

it("keeps inherited object keys out of structural control bindings", () => {
  const translation = createControlTranslation(
    { bindings: {} },
    { bindings: { prepared: { input: "filters", path: [] } } },
  );

  expect(translation.editor({ objectId: "toString", value: "local" })).toEqual([]);
});

it("compares inherited-looking structured keys by own entries", () => {
  expect(sameControlBindings({ toString: { input: "filters", path: [] } }, {})).toBe(false);
});

it("keeps inherited native semantic keys out of target cells", () => {
  const translation = createControlTranslation(
    { native: { cells: { toString: "live-control" } } },
    { native: { cells: {} } },
  );

  expect(translation.editor({ objectId: "live-control-0", value: "local" })).toEqual([]);
});
