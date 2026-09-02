import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { DocumentBase, resolveDocumentBase } from "../src/document/base.ts";

test("the active view base resolves from its document and survives runtime changes", async () => {
  const source = new DOMParser().parseFromString(
    '<html><head><base href="/report/"></head><body></body></html>',
    "text/html",
  );
  const href = resolveDocumentBase(source, "https://example.com/report/");
  const viewBase = new DocumentBase(source);
  viewBase.start(href);

  assert.equal(source.baseURI, "https://example.com/report/");

  source.querySelector("base")?.setAttribute("href", "https://example.com/");
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.equal(source.baseURI, "https://example.com/report/");
  viewBase.stop();

  source.querySelector("base")?.setAttribute("href", "https://example.com/");
  viewBase.start();

  assert.equal(source.baseURI, "https://example.com/report/");
  viewBase.stop();
});

test("the active view keeps ownership when an authored base becomes first", async () => {
  const source = new DOMParser().parseFromString(
    '<html><head><base href="./"><base href="https://assets.example/"></head><body></body></html>',
    "text/html",
  );
  const href = resolveDocumentBase(source, "https://example.com/site/pages/index.html");
  const viewBase = new DocumentBase(source);
  viewBase.start(href);

  source.querySelector("base")?.remove();
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.equal(source.baseURI, "https://example.com/site/pages/");
  assert.equal(source.querySelector("base")?.getAttribute("href"), href);
  viewBase.stop();
});
