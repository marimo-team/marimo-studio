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
  assert.equal(requiresDocumentReload(next, parse(next.documentElement.outerHTML), false), false);
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

test("structural shell changes reload an unchanged authored script", () => {
  const executable = '<script type="module">document.querySelector("button")?.focus()</script>';
  const current = parse(
    executable,
    '<main id="app-shell"><section><button id="run">Run</button></section></main>',
  );
  const structuralChanges = [
    '<main id="app-shell"><section><button id="save">Save</button></section></main>',
    '<main id="app-shell"><div><button id="run">Run</button></div></main>',
    '<main id="app-shell"><section><p>Ready</p><button id="run">Run</button></section></main>',
  ];

  for (const body of structuralChanges) {
    assert.equal(requiresDocumentReload(current, parse(executable, body), true), true);
  }
});

test("stylesheet changes preserve an unchanged authored script and shell", () => {
  const script = '<script type="module" src="app.js"></script>';
  const shell = '<main id="app-shell"><button id="run">Run</button></main>';
  const current = parse(`<style>button { color: red; }</style>${script}`, shell);
  const next = parse(`<style>button { color: blue; }</style>${script}`, shell);

  assert.equal(requiresDocumentReload(current, next, false), false);
});
