import { generate, parse, walk } from "css-tree";
import assert from "node:assert/strict";
import { afterEach, test, vi } from "vite-plus/test";

import { PresentationDocumentRetiredError } from "../src/document/session-startup.ts";
import {
  beginPresentationRefresh,
  readiness,
  setPresentationRefreshState,
} from "../src/readiness.ts";
import { generateViewCss } from "../src/view-styles/generator.ts";
import {
  collectViewClassTokens,
  initializeViewStyles,
  supportsViewStyleScope,
  ViewStyleController,
} from "../src/view-styles/runtime.ts";

const settleMutations = async (): Promise<void> => {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
};

const cssFacts = (css: string) => {
  const layers: string[] = [];
  const scopes: string[] = [];
  const keyframes: string[] = [];
  const selectors: string[] = [];
  const declarations: Array<[string, string]> = [];
  walk(parse(css), (node) => {
    if (node.type === "Atrule") {
      const prelude = node.prelude ? generate(node.prelude) : "";
      if (node.name === "layer") {
        layers.push(prelude);
      } else if (node.name === "scope") {
        scopes.push(prelude);
      } else if (node.name === "keyframes") {
        keyframes.push(prelude);
      }
    } else if (node.type === "Rule") {
      selectors.push(generate(node.prelude));
    } else if (node.type === "Declaration") {
      declarations.push([node.property, generate(node.value)]);
    }
  });
  return { declarations, keyframes, layers, scopes, selectors };
};

afterEach(() => {
  document.head.replaceChildren();
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

test("generated utilities stay scoped to authored content", async () => {
  const css = await generateViewCss(new Set(["[&>p]:text-red-500", "studio-view"]));
  const facts = cssFacts(css);

  assert.deepEqual(facts.layers, ["marimo-studio-utilities"]);
  assert.deepEqual(facts.scopes, ["(#app-shell) to ([data-marimo-cell-output])"]);
  assert.equal(
    facts.selectors.some((selector) => selector.includes(".studio-view")),
    true,
  );
  assert.equal(
    facts.selectors.some((selector) => selector.endsWith(">p")),
    true,
  );
});

test("concurrent generations isolate theme tokens and animation names", async () => {
  const [red, blue] = await Promise.all([
    generateViewCss(new Set(["animate-spin", "text-red-500"])),
    generateViewCss(new Set(["text-blue-600"])),
  ]);
  const redFacts = cssFacts(red);
  const blueFacts = cssFacts(blue);
  const redSelectors = redFacts.selectors.join(" ");
  const blueSelectors = blueFacts.selectors.join(" ");
  const animationValues = redFacts.declarations
    .filter(([property]) => property === "animation")
    .map(([, value]) => value);

  assert.match(redSelectors, /text-red-500/);
  assert.doesNotMatch(redSelectors, /text-blue-600/);
  assert.match(blueSelectors, /text-blue-600/);
  assert.doesNotMatch(blueSelectors, /text-red-500/);
  assert.deepEqual(redFacts.keyframes, ["marimo-studio-view-spin"]);
  assert.equal(animationValues.length > 0, true);
  assert.equal(
    animationValues.every((value) => value.includes("marimo-studio-view-spin")),
    true,
  );
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
  let generations = 0;
  const generatedTokens: string[][] = [];
  const controller = new ViewStyleController(async (tokens) => {
    generations += 1;
    generatedTokens.push([...tokens].sort());
    return `.generation-${generations}{}`;
  });
  const style = document.querySelector<HTMLStyleElement>("style")!;

  const initial = await controller.stage(document.querySelector("#app-shell")!);
  initial.commit();
  const initialCss = style.textContent;
  const next = document.createElement("main");
  next.id = "app-shell";
  next.className = "flex p-4";
  const staged = await controller.stage(next);

  staged.discard();
  assert.equal(style.textContent, initialCss);

  controller.observe();
  document.querySelector("[data-marimo-cell-output]")!.innerHTML =
    '<div class="bg-red-500 flex">Runtime output</div>';
  await settleMutations();
  assert.equal(generations, 2);

  document.querySelector("#app-shell")!.append(document.createElement("section"));
  await settleMutations();
  assert.equal(style.textContent, initialCss);
  assert.equal(generations, 2);

  document
    .querySelector("#app-shell")!
    .append(Object.assign(document.createElement("section"), { className: "studio-card" }));
  await settleMutations();
  assert.equal(generations, 3);
  assert.deepEqual(generatedTokens.at(-1), ["grid", "studio-card"]);
  assert.notEqual(style.textContent, initialCss);
  controller.disconnect();
});

test("a staged shell replacement retains its revision readiness owner", async () => {
  document.body.innerHTML = '<main id="app-shell" class="grid"></main>';
  let generations = 0;
  const generatedTokens: string[][] = [];
  const controller = new ViewStyleController(async (tokens) => {
    generations += 1;
    generatedTokens.push([...tokens].sort());
    return `.generation-${generations}{}`;
  });
  const initial = await controller.stage(document.querySelector("#app-shell")!);
  initial.commit();
  initial.finalize();
  controller.observe();
  readiness.start();
  readiness.setRuntime("ready");
  readiness.setHosts(["ready"]);
  const revisionClaim = beginPresentationRefresh("document");

  const replacement = document.createElement("main");
  replacement.id = "app-shell";
  replacement.className = "flex p-4";
  const staged = await controller.stage(replacement);
  staged.commit();
  document.querySelector("#app-shell")!.replaceWith(replacement);
  staged.finalize();
  setPresentationRefreshState(revisionClaim, "ready");
  await settleMutations();

  assert.equal(generations, 2);
  assert.deepEqual(generatedTokens.at(-1), ["flex", "p-4"]);
  assert.equal(readiness.snapshot().page, "ready");
  controller.disconnect();
});

test("value text updates do not regenerate authored utility CSS", async () => {
  document.body.innerHTML = `
    <main id="app-shell" class="grid">
      <strong mo-value="count">1</strong>
    </main>
  `;
  let calls = 0;
  const controller = new ViewStyleController(async (tokens) => {
    calls += 1;
    return `/* ${[...tokens].sort().join(" ")} */`;
  });
  await controller.refresh();
  controller.observe();

  document.querySelector("[mo-value]")!.textContent = "2";
  await settleMutations();

  assert.equal(calls, 1);
  controller.disconnect();
});

test("initial generation includes classes added while the generator loads", async () => {
  document.body.innerHTML = '<main id="app-shell" class="grid"></main>';
  let release: (() => void) | undefined;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let calls = 0;
  const generatedTokens: string[][] = [];
  const controller = new ViewStyleController(async (tokens) => {
    calls += 1;
    generatedTokens.push([...tokens].sort());
    if (calls === 1) {
      await gate;
    }
    return `.generation-${calls}{}`;
  });
  controller.observe();

  const ready = controller.refresh();
  document
    .querySelector("#app-shell")!
    .append(Object.assign(document.createElement("section"), { className: "pl-[37px]" }));
  await settleMutations();
  release?.();
  await ready;

  assert.deepEqual(generatedTokens.at(-1), ["grid", "pl-[37px]"]);
  controller.disconnect();
});

test("a live utility regeneration failure becomes a presentation diagnostic", async () => {
  document.body.innerHTML = '<main id="app-shell" class="grid"></main>';
  let calls = 0;
  const controller = new ViewStyleController(async () => {
    calls += 1;
    if (calls > 1) {
      throw new Error("generator failed");
    }
    return "/* grid */";
  });
  await controller.refresh();
  controller.observe();

  document.querySelector("#app-shell")!.classList.add("p-4");
  await settleMutations();

  const diagnostic = document.querySelector<HTMLElement>("[data-marimo-studio-style-error]");
  assert.equal(document.documentElement.dataset.marimoStudioStyles, "error");
  assert.equal(diagnostic?.dataset.marimoDiagnosticCode, "view-styles-failed");
  assert.equal(diagnostic?.dataset.marimoDiagnosticScope, "presentation");
  assert.equal(
    diagnostic?.textContent,
    "View styling could not update. The authored view remains available.",
  );
  controller.disconnect();
});

test("late style initialization clears the watchdog diagnostic", async () => {
  document.body.innerHTML = '<main id="app-shell" class="p-4"></main>';
  globalThis.__MARIMO_STUDIO_STYLE_TIMEOUT__ = setTimeout(() => {}, 60_000);
  await initializeViewStyles(false);
  assert.notEqual(document.querySelector("[data-marimo-studio-style-error]"), null);

  await initializeViewStyles(true);

  assert.equal(document.documentElement.dataset.marimoStudioStyles, "ready");
  assert.equal(document.querySelector("[data-marimo-studio-style-error]"), null);
});

test("unsupported scope leaves authored CSS available with a visible diagnostic", async () => {
  document.body.innerHTML = '<main id="app-shell"></main>';

  await initializeViewStyles(false);

  assert.equal(supportsViewStyleScope({}), false);
  assert.equal(document.documentElement.dataset.marimoStudioStyles, "error");
  assert.match(
    document.querySelector("[data-marimo-studio-style-error]")!.textContent ?? "",
    /CSS @scope support/,
  );
});

test("document retirement cancels style initialization without a diagnostic", async () => {
  document.body.innerHTML = '<main id="app-shell" class="p-4"></main>';
  const lifetime = new AbortController();
  const retirement = new PresentationDocumentRetiredError();
  const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

  const initializing = initializeViewStyles(true, lifetime.signal);
  lifetime.abort(retirement);

  await assert.rejects(initializing, (cause: unknown) => cause === retirement);
  assert.equal(document.querySelector("[data-marimo-studio-style-error]"), null);
  assert.equal(consoleError.mock.calls.length, 0);
});

test("an active style initialization failure remains visible", async () => {
  const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

  const diagnostic = await initializeViewStyles(true, new AbortController().signal);

  assert.equal(diagnostic?.code, "view-styles-failed");
  assert.equal(
    diagnostic?.message,
    "View styling could not start. The authored view remains available.",
  );
  assert.equal(document.documentElement.dataset.marimoStudioStyles, "error");
  assert.notEqual(document.querySelector("[data-marimo-studio-style-error]"), null);
  assert.equal(consoleError.mock.calls.length, 1);
});
