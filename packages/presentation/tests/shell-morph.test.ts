import { expect, test } from "vite-plus/test";

import { morphAuthoredShell, sameProjectionHostTopology } from "../src/document/shell-morph.ts";

const shell = (source: string): HTMLElement => {
  const parsed = new DOMParser().parseFromString(source, "text/html");
  return document.importNode(parsed.querySelector<HTMLElement>("#app-shell")!, true);
};

test("authored shell updates preserve mounted projection content", () => {
  const current = shell(`
    <main id="app-shell" class="current">
      <h1>Before</h1>
      <svg aria-label="mark"><circle r="4" fill="red"></circle></svg>
      <marimo-output id="summary" value="summary" data-hx-preserve></marimo-output>
    </main>
  `);
  document.body.replaceChildren(current);
  const host = current.querySelector<HTMLElement>("marimo-output")!;
  const rendered = document.createElement("strong");
  rendered.textContent = "Current total: 42";
  host.append(rendered);
  const next = shell(`
    <main id="app-shell" class="updated">
      <h1>After</h1>
      <svg aria-label="updated mark"><circle r="6" fill="blue"></circle></svg>
      <marimo-output
        id="summary"
        value="summary"
        class="featured"
        data-hx-preserve
      ></marimo-output>
    </main>
  `);

  expect(sameProjectionHostTopology(current, next)).toBe(true);
  morphAuthoredShell(current, next);

  expect(document.querySelector("#app-shell")).toBe(current);
  expect(current.className).toBe("updated");
  expect(current.querySelector("h1")?.textContent).toBe("After");
  expect(current.querySelector("svg")?.getAttribute("aria-label")).toBe("updated mark");
  expect(current.querySelector("circle")?.getAttribute("fill")).toBe("blue");
  expect(current.querySelector("marimo-output")).toBe(host);
  expect(host.className).toBe("featured");
  expect(host.firstChild).toBe(rendered);
});

test("projection host movement requires a document reload", () => {
  const current = shell(`
    <main id="app-shell">
      <marimo-output id="summary" value="summary" data-hx-preserve></marimo-output>
    </main>
  `);
  const next = shell(`
    <main id="app-shell">
      <section>
        <marimo-output id="summary" value="summary" data-hx-preserve></marimo-output>
      </section>
    </main>
  `);

  expect(sameProjectionHostTopology(current, next)).toBe(false);
});

test("wrapper element changes are rejected before the live shell is mutated", () => {
  const current = shell(`
    <main id="app-shell">
      <section class="before">
        <marimo-output id="summary" value="summary" data-hx-preserve></marimo-output>
      </section>
    </main>
  `);
  const next = shell(`
    <main id="app-shell">
      <div class="after">
        <marimo-output id="summary" value="summary" data-hx-preserve></marimo-output>
      </div>
    </main>
  `);
  document.body.replaceChildren(current);
  const before = current.outerHTML;

  expect(sameProjectionHostTopology(current, next)).toBe(false);
  expect(() => morphAuthoredShell(current, next)).toThrow(
    "Projection host topology changed during the document refresh",
  );
  expect(current.outerHTML).toBe(before);
});
