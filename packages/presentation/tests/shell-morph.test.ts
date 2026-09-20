import { expect, test } from "vite-plus/test";

import { morphAuthoredShell, sameProjectionHostTopology } from "../src/document/shell-morph.ts";

const shell = (source: string): HTMLElement => {
  const parsed = new DOMParser().parseFromString(source, "text/html");
  return document.importNode(parsed.querySelector<HTMLElement>("#app-shell")!, true);
};

test("authored shell updates preserve mounted projection content", () => {
  const current = shell(`
    <main id="app-shell">
      <h1>Before</h1>
      <svg aria-label="mark"><circle></circle></svg>
      <marimo-output id="summary" value="summary" data-marimo-studio-preserve></marimo-output>
    </main>
  `);
  document.body.replaceChildren(current);
  const host = current.querySelector<HTMLElement>("marimo-output")!;
  const rendered = document.createElement("strong");
  rendered.textContent = "Current total: 42";
  host.append(rendered);
  host.dataset.marimoLensLabel = "Summary";
  host.dataset.marimoLensDetail = "Previous quarter";
  const next = shell(`
    <main id="app-shell">
      <h1>After</h1>
      <svg aria-label="updated mark"><circle></circle></svg>
      <marimo-output
        id="summary"
        value="summary"
        class="featured"
        data-marimo-lens-label="Revenue"
        data-marimo-studio-preserve
      ></marimo-output>
    </main>
  `);

  expect(sameProjectionHostTopology(current, next)).toBe(true);
  morphAuthoredShell(current, next);

  expect(document.querySelector("#app-shell")).toBe(current);
  expect(current.querySelector("h1")?.textContent).toBe("After");
  expect(current.querySelector("svg")?.getAttribute("aria-label")).toBe("updated mark");
  expect(current.querySelector("marimo-output")).toBe(host);
  expect(host.className).toBe("featured");
  expect(host.firstChild).toBe(rendered);
  expect(host.dataset.marimoLensLabel).toBe("Revenue");
  expect(host.dataset.marimoLensDetail).toBeUndefined();
});

test("projection host movement requires a document reload", () => {
  const current = shell(`
    <main id="app-shell">
      <marimo-output id="summary" value="summary" data-marimo-studio-preserve></marimo-output>
    </main>
  `);
  const next = shell(`
    <main id="app-shell">
      <section>
        <marimo-output id="summary" value="summary" data-marimo-studio-preserve></marimo-output>
      </section>
    </main>
  `);

  expect(sameProjectionHostTopology(current, next)).toBe(false);
});

test("wrapper element changes are rejected before the live shell is mutated", () => {
  const current = shell(`
    <main id="app-shell">
      <section class="before">
        <marimo-output id="summary" value="summary" data-marimo-studio-preserve></marimo-output>
      </section>
    </main>
  `);
  const next = shell(`
    <main id="app-shell">
      <div class="after">
        <marimo-output id="summary" value="summary" data-marimo-studio-preserve></marimo-output>
      </div>
    </main>
  `);
  document.body.replaceChildren(current);
  const wrapper = current.querySelector("section")!;
  const host = current.querySelector("marimo-output")!;

  expect(sameProjectionHostTopology(current, next)).toBe(false);
  expect(() => morphAuthoredShell(current, next)).toThrow(
    "Projection host topology changed during the document refresh",
  );
  expect(current.querySelector("section")).toBe(wrapper);
  expect(wrapper.firstElementChild).toBe(host);
});

test("shell updates resolve authored hosts beside native output with matching IDs", () => {
  const current = shell(`
    <main id="app-shell">
      <marimo-output id="outer" value="outer" data-marimo-studio-preserve>
        <div data-marimo-cell-output>
          <marimo-output id="summary" value="native" data-marimo-studio-preserve>Native content</marimo-output>
        </div>
      </marimo-output>
      <marimo-output id="summary" value="summary" data-marimo-studio-preserve>Authored content</marimo-output>
    </main>
  `);
  document.body.replaceChildren(current);
  const native = current.querySelector("[data-marimo-cell-output] marimo-output")!;
  const nativeParent = native.parentElement;
  const authored = current.lastElementChild!;
  const next = shell(`
    <main id="app-shell">
      <marimo-output id="outer" value="outer" data-marimo-studio-preserve></marimo-output>
      <marimo-output id="summary" value="summary" class="updated" data-marimo-studio-preserve></marimo-output>
    </main>
  `);

  morphAuthoredShell(current, next);

  expect(current.lastElementChild).toBe(authored);
  expect(authored.className).toBe("updated");
  expect(authored.textContent).toBe("Authored content");
  expect(native.parentElement).toBe(nativeParent);
  expect(native.textContent).toBe("Native content");
  expect(native.getAttribute("value")).toBe("native");
});
