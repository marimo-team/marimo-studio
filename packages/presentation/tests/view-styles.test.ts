import assert from "node:assert/strict";
import { afterEach, test } from "vite-plus/test";

import { generateViewCss } from "../src/view-styles/generator.ts";
import {
  collectViewClassTokens,
  initializeViewStyles,
  ViewStyleController,
} from "../src/view-styles/runtime.ts";

const settleMutations = async (): Promise<void> => {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
};

afterEach(() => {
  document.head.replaceChildren();
  document.body.replaceChildren();
});

test("utility generation scopes variants and normalizes borders", async () => {
  const css = await generateViewCss(
    new Set([
      "[&>p]:text-red-500",
      'before:content-["Ready"]',
      "border",
      "border-border",
      "border-x-2",
    ]),
  );

  assert.match(css, /\\\[\\&\\>p\\\]\\:text-red-500>p/);
  assert.match(css, />p:where\(\[data-marimo-studio-authored\]\)/);
  assert.match(css, /:where\(\[data-marimo-studio-authored\]\)::before/);
  assert.match(css, /#app-shell\{[^}]*--colors-red-500/);
  assert.match(css, /border-width:1px;border-style:solid/);
  assert.match(css, /border-inline-width:2px;border-inline-style:solid/);
});

test("generations isolate theme tokens and namespace animation keyframes", async () => {
  const [red, blue] = await Promise.all([
    generateViewCss(new Set(["animate-spin", "text-red-500"])),
    generateViewCss(new Set(["text-blue-600"])),
  ]);

  assert.match(red, /--colors-red-500/);
  assert.doesNotMatch(red, /--colors-blue-600/);
  assert.match(red, /@keyframes marimo-studio-view-spin/);
  assert.match(red, /animation:marimo-studio-view-spin /);
  assert.doesNotMatch(red, /@keyframes spin/);
  assert.match(blue, /--colors-blue-600/);
  assert.doesNotMatch(blue, /--colors-red-500/);
});

test("a later component class overrides an authored utility", async () => {
  document.body.innerHTML = '<main id="app-shell"><section class="card p-4"></section></main>';
  const controller = new ViewStyleController();
  const staged = await controller.stage(document.querySelector("#app-shell")!);
  staged.commit();
  document.head.insertAdjacentHTML("beforeend", "<style>.card { padding: 37px; }</style>");

  assert.equal(getComputedStyle(document.querySelector("section")!).padding, "37px");
  controller.disconnect();
});

test("class collection stops at Marimo-owned output", () => {
  document.body.innerHTML = `
    <main id="app-shell" class="grid">
      <section class="p-4">
        <marimo-cell class="rounded-lg">
          <div data-marimo-cell-output>
            <div class="flex bg-red-500">Runtime output</div>
          </div>
        </marimo-cell>
      </section>
    </main>
  `;

  assert.deepEqual([...collectViewClassTokens(document.querySelector("#app-shell")!)].sort(), [
    "grid",
    "p-4",
    "rounded-lg",
  ]);
});

test("staged utility CSS commits atomically and ignores output mutations", async () => {
  document.body.innerHTML = `
    <main id="app-shell" class="grid">
      <marimo-cell><div data-marimo-cell-output></div></marimo-cell>
    </main>
  `;
  const controller = new ViewStyleController(async (tokens) => {
    const tokenList = [...tokens].sort().join(" ");
    return `/* ${tokenList} */`;
  });
  const style = document.querySelector<HTMLStyleElement>("style")!;

  const initial = await controller.stage(document.querySelector("#app-shell")!);
  initial.commit();
  const next = document.createElement("main");
  next.id = "app-shell";
  next.className = "flex p-4";
  const staged = await controller.stage(next);

  assert.equal(style.textContent, "/* grid */");
  staged.discard();
  assert.equal(style.textContent, "/* grid */");

  controller.observe();
  document.querySelector("[data-marimo-cell-output]")!.innerHTML =
    '<div class="bg-red-500 flex">Runtime output</div>';
  await settleMutations();
  assert.equal(style.textContent, "/* grid */");

  document
    .querySelector("#app-shell")!
    .append(Object.assign(document.createElement("section"), { className: "studio-card" }));
  await settleMutations();
  assert.equal(style.textContent, "/* grid studio-card */");
  controller.disconnect();
});

test("late style initialization clears the watchdog diagnostic", async () => {
  document.body.innerHTML = `
    <main id="app-shell" class="p-4"></main>
    <div data-marimo-studio-style-error role="alert">Style startup failed</div>
  `;
  const browser = globalThis as typeof globalThis & {
    __MARIMO_STUDIO_STYLE_TIMEOUT__?: ReturnType<typeof setTimeout>;
  };
  browser.__MARIMO_STUDIO_STYLE_TIMEOUT__ = setTimeout(() => {}, 60_000);

  await initializeViewStyles();

  assert.equal(document.documentElement.dataset.marimoStudioStyles, "ready");
  assert.equal(document.querySelector("[data-marimo-studio-style-error]"), null);
});
