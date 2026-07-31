import { assertEquals } from "@std/assert";

import { viewNavigationForUrl } from "../src/view-navigation.ts";

const selection = (href: string, currentView = "novice") =>
  viewNavigationForUrl({
    href,
    origin: "https://example.test",
    runtimeUrl: "/proxy/token/",
    views: ["novice", "intermediate", "expert"],
    currentView,
  });

Deno.test("configured view URLs resolve beneath Marimo's base path", () => {
  const base = new URL("/proxy/token/", "https://example.test");

  assertEquals(
    selection(new URL("./intermediate/", base).href),
    { view: "intermediate", current: false },
  );
  assertEquals(
    selection("https://example.test/proxy/token/expert/"),
    { view: "expert", current: false },
  );
});

Deno.test("the active configured view resolves as a navigation no-op", () => {
  assertEquals(
    selection("https://example.test/proxy/token/novice/"),
    { view: "novice", current: true },
  );
});

Deno.test("view navigation leaves other links to the browser", () => {
  assertEquals(
    selection("https://other.test/proxy/token/intermediate/"),
    undefined,
  );
  assertEquals(selection("https://example.test/intermediate/"), undefined);
  assertEquals(
    selection("https://example.test/proxy/intermediate/"),
    undefined,
  );
  assertEquals(
    selection("https://example.test/proxy/token/intermediate/?region=eu"),
    undefined,
  );
  assertEquals(
    selection("https://example.test/proxy/token/intermediate/#results"),
    undefined,
  );
  assertEquals(
    selection("https://example.test/proxy/token/missing/"),
    undefined,
  );
});
