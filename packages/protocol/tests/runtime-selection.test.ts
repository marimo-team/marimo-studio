import { expect, test } from "vite-plus/test";

import { runtimeIdFromSearch, selectRuntimeInUrl } from "../src/runtime-selection";

test("runtime selection round-trips choices without changing authored URL state", () => {
  expect(runtimeIdFromSearch("?region=emea")).toBe("server");
  const url = selectRuntimeInUrl("https://example.test/dashboard/?x=1#results", "wasm");

  expect(new URL(url).searchParams.get("runtime")).toBe("wasm");
  expect(new URL(url).hash).toBe("#results");
  expect(runtimeIdFromSearch(new URL(url).search)).toBe("wasm");

  const serverUrl = selectRuntimeInUrl("https://example.test/dashboard/", "server", "wasm");
  const wasmUrl = selectRuntimeInUrl(
    "https://example.test/dashboard/?runtime=server#results",
    "wasm",
    "wasm",
  );

  expect(new URL(serverUrl).searchParams.get("runtime")).toBe("server");
  expect(new URL(wasmUrl).searchParams.has("runtime")).toBe(false);
  expect(new URL(wasmUrl).hash).toBe("#results");
  expect(runtimeIdFromSearch(new URL(wasmUrl).search, "wasm")).toBe("wasm");
});
