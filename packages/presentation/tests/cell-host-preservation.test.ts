import assert from "node:assert/strict";
import { afterEach, test } from "vite-plus/test";

import { projectionHosts } from "../src/projections/host-runtime.ts";
import { ViewStyleController } from "../src/view-styles/runtime.ts";

afterEach(() => {
  document.head.replaceChildren();
  document.body.replaceChildren();
});

test("a shell swap updates authored cell attributes without replacing its output", async () => {
  // HTMX checks browser XPath and CSS escaping APIs that jsdom exposes incompletely.
  const evaluate = XPathExpression.prototype.evaluate;
  XPathExpression.prototype.evaluate = function (contextNode, type = XPathResult.ANY_TYPE, result) {
    return evaluate.call(this, contextNode, type, result);
  };
  Object.defineProperty(globalThis, "CSS", {
    configurable: true,
    value: { escape: (value: string) => value },
  });
  const { default: htmx } = await import("htmx.org");
  document.body.innerHTML = `
    <main id="app-shell">
      <marimo-cell name="summary" class="old" style="color: red" title="Old title">
        <div data-marimo-cell-output><button>Live control</button></div>
      </marimo-cell>
    </main>
  `;
  projectionHosts.prepare(document);
  const liveHost = document.querySelector<HTMLElement>("marimo-cell")!;
  const liveOutput = liveHost.querySelector("[data-marimo-cell-output]");
  liveHost.dataset.state = "ready";
  liveHost.dataset.runtimeCellId = "runtime-cell-1";
  liveHost.dataset.marimoDiagnosticCode = "stale-runtime-diagnostic";
  liveHost.style.setProperty("--_marimo-cell-measured-height", "120px");

  const nextDocument = new DOMParser().parseFromString(
    `
      <main id="app-shell">
        <marimo-cell
          name="summary"
          class="new p-6"
          style="color: blue"
          aria-label="Updated summary"
          data-skeleton="none"
        ></marimo-cell>
      </main>
    `,
    "text/html",
  );
  projectionHosts.prepare(nextDocument);
  const nextShell = nextDocument.querySelector("#app-shell")!;
  const styles = new ViewStyleController(async (tokens) => `/* ${[...tokens].sort().join(" ")} */`);
  const staged = await styles.stage(nextShell);

  const swap = (
    htmx as unknown as {
      swap: (target: Element, content: string, options: { swapStyle: string }) => void;
    }
  ).swap;
  swap(document.querySelector("#app-shell")!, nextShell.outerHTML, { swapStyle: "outerHTML" });
  projectionHosts.preserve(nextShell, document);
  staged.commit();

  const updatedHost = document.querySelector<HTMLElement>("marimo-cell")!;
  assert.equal(updatedHost, liveHost);
  assert.equal(updatedHost.querySelector("[data-marimo-cell-output]"), liveOutput);
  assert.equal(updatedHost.className, "new p-6");
  assert.equal(updatedHost.style.color, "blue");
  assert.equal(updatedHost.style.getPropertyValue("--_marimo-cell-measured-height"), "120px");
  assert.equal(updatedHost.getAttribute("aria-label"), "Updated summary");
  assert.equal(updatedHost.getAttribute("data-skeleton"), "none");
  assert.equal(updatedHost.hasAttribute("title"), false);
  assert.equal(updatedHost.dataset.state, "ready");
  assert.equal(updatedHost.dataset.runtimeCellId, "runtime-cell-1");
  assert.equal(updatedHost.dataset.marimoDiagnosticCode, "stale-runtime-diagnostic");
  assert.equal(document.querySelector("style")?.textContent, "/* new p-6 */");
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
  liveHost.dataset.runtimeCellId = "runtime-cell-id";

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
  assert.equal(liveHost.dataset.runtimeCellId, "runtime-cell-id");
});
