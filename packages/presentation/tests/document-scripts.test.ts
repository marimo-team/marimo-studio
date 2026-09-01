import assert from "node:assert/strict";
import { test } from "vite-plus/test";

import { hasAuthoredScripts, requiresDocumentReload } from "../src/document/scripts.ts";

const parse = (head = "", body = "<main id='app-shell'></main>"): Document =>
  new DOMParser().parseFromString(
    `<!doctype html><html><head>${head}</head><body>${body}</body></html>`,
    "text/html",
  );

test("authored scripts use a native document reload lifecycle", () => {
  const current = parse(
    '<script data-marimo-studio-runtime type="module" src="runtime.js"></script>',
  );
  const next = parse(
    '<script data-marimo-studio-runtime type="module" src="runtime.js"></script>',
    '<main id="app-shell"><script type="module">import "./app.js"</script></main>',
  );

  assert.equal(hasAuthoredScripts(current), false);
  assert.equal(hasAuthoredScripts(next), true);
  assert.equal(requiresDocumentReload(current, next, true), true);
  const unchanged = next.implementation.createHTMLDocument();
  unchanged.replaceChild(
    unchanged.importNode(next.documentElement, true),
    unchanged.documentElement,
  );
  assert.equal(requiresDocumentReload(next, unchanged, false), false);
  const executable = '<script type="module" src="app.js"></script>';
  assert.equal(
    requiresDocumentReload(
      parse(executable, '<main id="app-shell"><p>Current</p></main>'),
      parse(executable, '<main id="app-shell"><p>Updated</p></main>'),
      true,
    ),
    true,
  );
  assert.equal(
    hasAuthoredScripts(parse('<script type="importmap">{"imports":{"app":"./app.js"}}</script>')),
    true,
  );
});

test("data blocks and runtime output scripts do not change the document lifecycle", () => {
  const current = parse(
    '<script type="application/ld+json">{"name":"Report"}</script>',
    `<main id="app-shell">
      <marimo-cell>
        <div data-marimo-cell-output><script>window.output = true</script></div>
      </marimo-cell>
    </main>`,
  );
  const next = parse('<script type="application/json">{"state":"ready"}</script>');

  assert.equal(hasAuthoredScripts(current), false);
  assert.equal(hasAuthoredScripts(next), false);
  assert.equal(requiresDocumentReload(current, next, true), false);
});
