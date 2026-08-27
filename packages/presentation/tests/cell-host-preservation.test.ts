import assert from "node:assert/strict";
import { afterEach, test } from "vite-plus/test";

import { projectionHosts } from "../src/projections/host-runtime.ts";

afterEach(() => {
  document.head.replaceChildren();
  document.body.replaceChildren();
});

test("a shell swap updates an authored cell without replacing its output", () => {
  document.body.innerHTML = `
    <main id="app-shell">
      <marimo-cell name="summary" class="old">
        <div data-marimo-cell-output><button>Live control</button></div>
      </marimo-cell>
    </main>
  `;
  projectionHosts.prepare(document);
  const liveHost = document.querySelector<HTMLElement>("marimo-cell")!;
  const liveOutput = liveHost.querySelector("[data-marimo-cell-output]");
  liveHost.dataset.state = "ready";
  liveHost.style.setProperty("--_marimo-cell-measured-height", "120px");

  const nextDocument = new DOMParser().parseFromString(
    `
      <main id="app-shell">
        <marimo-cell
          name="summary"
          class="new p-6"
        ></marimo-cell>
      </main>
    `,
    "text/html",
  );
  projectionHosts.prepare(nextDocument);
  const nextShell = document.importNode(
    nextDocument.querySelector<HTMLElement>("#app-shell")!,
    true,
  );
  const staged = projectionHosts.stagePreservation(nextShell, document);
  const current = document.querySelector<HTMLElement>("#app-shell")!;
  current.before(nextShell);
  staged.commit();
  current.remove();
  staged.finalize();

  const updatedHost = document.querySelector<HTMLElement>("marimo-cell")!;
  assert.equal(updatedHost, liveHost);
  assert.equal(updatedHost.querySelector("[data-marimo-cell-output]"), liveOutput);
  assert.equal(updatedHost.className, "new p-6");
  assert.equal(updatedHost.style.getPropertyValue("--_marimo-cell-measured-height"), "120px");
  assert.equal(updatedHost.dataset.state, "ready");
});

test("a shell refresh updates a rich output host around its mounted renderer", () => {
  document.body.innerHTML = `
    <main id="app-shell">
      <marimo-output value="report.table" class="old">
        <div data-marimo-cell-output><button>Native table action</button></div>
      </marimo-output>
    </main>
  `;
  projectionHosts.prepare(document);
  const liveHost = document.querySelector<HTMLElement>("marimo-output")!;
  const liveOutput = liveHost.querySelector("[data-marimo-cell-output]");
  liveHost.dataset.state = "ready";

  const nextDocument = new DOMParser().parseFromString(
    `
      <main id="app-shell">
        <marimo-output value="report.table" class="new p-4"></marimo-output>
      </main>
    `,
    "text/html",
  );
  projectionHosts.prepare(nextDocument);
  const nextShell = nextDocument.querySelector("#app-shell")!;

  projectionHosts.preserve(nextShell, document);

  assert.equal(liveHost.querySelector("[data-marimo-cell-output]"), liveOutput);
  assert.equal(liveHost.className, "new p-4");
  assert.equal(liveHost.dataset.state, "ready");
});
