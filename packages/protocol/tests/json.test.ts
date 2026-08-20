import { expect, it } from "vite-plus/test";

import { jsonCodec } from "../src/json.ts";
import {
  jsonObjectSchema,
  jsonValueSchema,
  MAX_JSON_DEPTH,
  type JsonValue,
} from "../src/runtime-config.ts";

it("preserves reserved keys through the protocol JSON boundary", () => {
  const parsed = jsonObjectSchema.parse(
    JSON.parse('{"__proto__":{"nested":{"__proto__":"kept"}}}'),
  );
  const root = jsonObjectSchema.parse(parsed.__proto__);
  const nested = jsonObjectSchema.parse(root.nested);

  expect(Object.hasOwn(parsed, "__proto__")).toBe(true);
  expect(Object.hasOwn(nested, "__proto__")).toBe(true);
  expect(nested.__proto__).toBe("kept");
  expect(Object.hasOwn(Object.prototype, "nested")).toBe(false);
});

it("applies portable depth, number, and Unicode bounds", () => {
  let deep: JsonValue = null;
  for (let depth = 0; depth < 5_000; depth += 1) {
    deep = Object.fromEntries([["child", deep]]);
  }

  expect(() => jsonValueSchema.parse(deep)).toThrow(/nesting depth/);
  expect(() => jsonValueSchema.parse(Number.MAX_SAFE_INTEGER + 1)).toThrow(/safe range/);
  expect(() => jsonValueSchema.parse("\ud800")).toThrow(/Unicode scalar/);
  expect(MAX_JSON_DEPTH).toBe(256);
});

it("accepts shared aliases and rejects active container cycles", () => {
  const shared = { value: 1 };
  expect(jsonValueSchema.parse([shared, shared])).toEqual([{ value: 1 }, { value: 1 }]);

  const cyclic: CyclicValue = {};
  cyclic.child = cyclic;
  expect(() => jsonValueSchema.parse(cyclic)).toThrow(/cyclic container/);
});

interface CyclicValue {
  child?: CyclicValue;
}

it("rejects duplicate keys and lossy number lexemes before schema decoding", () => {
  const codec = jsonCodec(jsonValueSchema);

  expect(codec.safeDecode('{"value":1,"value":2}').success).toBe(false);
  expect(codec.safeDecode('{"value":0.99999999999999999}').success).toBe(false);
});
