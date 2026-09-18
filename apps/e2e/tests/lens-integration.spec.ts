import type { FrameLocator, Locator, Page } from "@playwright/test";

import { readFile, rm } from "node:fs/promises";
import { resolve } from "node:path";
import { z } from "zod";

import type { StudioCli } from "./studio-cli.ts";

import { fixtureDirectory, workspaceDirectory } from "../scripts/paths.mjs";
import {
  expect,
  labeledSlider,
  test,
  waitForViewPreview,
  workspaceCreatedViewHtmlPath,
  workspaceNotebookPath,
  writeWorkspaceFile,
} from "./fixture.ts";

test.describe.configure({ timeout: 180_000 });

const contextSchema = z.object({
  references: z.object({
    selections: z.array(
      z.object({
        id: z.string(),
        note: z.string(),
        target: z.object({
          domSelector: z.string().optional(),
          sources: z
            .array(z.object({ cellId: z.string(), selector: z.string().nullable() }))
            .default([]),
        }),
        description: z
          .object({
            label: z.string(),
            renderSource: z
              .object({
                path: z.string(),
                symbol: z.string().optional(),
              })
              .optional(),
          })
          .optional(),
        domHint: z
          .object({ tag: z.string(), text: z.string().optional(), path: z.string().optional() })
          .optional(),
        cells: z.array(z.object({ id: z.string(), status: z.string() })),
        snapshot: z.object({ status: z.string() }),
      }),
    ),
  }),
  images: z.record(z.string(), z.string()),
});

async function openView(
  page: Page,
  cli: StudioCli,
  provider: "vanilla" | "react" | "svelte",
  mount: "projected" | "notebook" | "installed" | "anonymous" = "projected",
) {
  const fixtures = resolve(fixtureDirectory, "lens");
  await rm(resolve(workspaceDirectory, "__marimo__/studio/notebook"), {
    recursive: true,
    force: true,
  });
  let notebook = await readFile(resolve(fixtures, "notebook.py.txt"), "utf8");
  if (mount === "notebook") {
    notebook = notebook.replace(
      "def feedback(Lens, STUDIO_RESULT_SELECTOR):",
      "def feedback(Lens, STUDIO_RESULT_SELECTOR, scale):\n    scale.value",
    );
  }
  if (mount === "installed" || mount === "anonymous") {
    notebook = notebook
      .replace(
        "def feedback(Lens, STUDIO_RESULT_SELECTOR):\n    lens = Lens(dom_selector=STUDIO_RESULT_SELECTOR)\n    return (lens,)",
        mount === "anonymous"
          ? "def feedback(Lens, mo):\n    mo.output.append(Lens())\n    return"
          : "def feedback():\n    return",
      )
      .replace("html, json, lens, mo", "html, json, mo")
      .replace(
        "    mo.stop(not submit.value)",
        "    mo.stop(not submit.value)\n    import marimo_lens.agent as _agent\n    _lens = _agent.connect()",
      )
      .replaceAll("lens.context()", "_lens.context()")
      .replaceAll("lens.resolve(", "_lens.resolve(");
    if (mount === "installed") {
      notebook = notebook
        .replace("    from marimo_lens import Lens\n", "")
        .replace("    from marimo_studio import STUDIO_RESULT_SELECTOR\n", "")
        .replace("return Lens, STUDIO_RESULT_SELECTOR, html, json, mo", "return html, json, mo");
    }
  }
  if (provider !== "vanilla")
    notebook = notebook.replace("Lens(dom_selector=STUDIO_RESULT_SELECTOR)", "Lens()");
  await writeWorkspaceFile(workspaceNotebookPath, notebook);
  await cli.addWorkspaceView(workspaceNotebookPath, "lens", `marimo-studio/${provider}:default`);
  const source = { vanilla: "index.html", react: "App.tsx", svelte: "App.svelte" }[provider];
  const destination = provider === "vanilla" ? source : `src/${source}`;
  let document = await readFile(
    resolve(fixtures, provider === "vanilla" ? source : `${source}.txt`),
    "utf8",
  );
  if (mount !== "projected")
    document = document.replace('<marimo-output value="lens"></marimo-output>', "");
  if (mount === "installed")
    document = document.replace('<marimo-output id="rich" value="rich"></marimo-output>', "");
  await writeWorkspaceFile(
    resolve(workspaceDirectory, "__marimo__/studio/notebook/lens", destination),
    document,
  );
  await cli.buildWorkspaceView("lens");
  await page.goto("/studio/lens/?file=notebook.py");
  const view = await waitForViewPreview(page, "lens", "server", 120_000);
  await expect(view.getByRole("button", { name: "Select a target", exact: true })).toHaveCount(1);
  return view;
}

for (const mount of ["notebook", "installed", "anonymous"] as const) {
  test(`Development preview mounts ${mount} Lens and preserves feedback through rebuild`, async ({
    page,
    studioCli,
  }, testInfo) => {
    const view = await openView(page, studioCli, "vanilla", mount);
    await expect(view.locator("[data-marimo-lens-view-conflict]")).toHaveCount(0);
    await select(view, view.locator("#scalar"), "Preview feedback");
    expect((await inspect(view)).references.selections).toMatchObject([
      { note: "Preview feedback" },
    ]);
    await select(view, view.locator("#intro"), "Make this heading clearer");
    const feedback = await capturedContext(view, 2);
    expect(feedback.references.selections[1]).toMatchObject({
      note: "Make this heading clearer",
      target: { sources: [] },
      cells: [],
      description: { label: "Introduction", renderSource: { path: "index.html" } },
    });
    expect(feedback.images[feedback.references.selections[1]!.id]).toBe("89504e470d0a1a0a");
    const source = workspaceCreatedViewHtmlPath("lens");
    await writeWorkspaceFile(
      source,
      (await readFile(source, "utf8")).replaceAll("Lens projections", "Rebuilt preview"),
    );
    await studioCli.buildWorkspaceView("lens");
    await expect(view.getByRole("heading", { name: "Rebuilt preview" })).toBeVisible();
    await expect(view.getByRole("button", { name: "Select a target", exact: true })).toHaveCount(1);
    await expect(
      view.getByRole("button", { name: "Open selections, 2 open, 0 in history" }),
    ).toBeVisible();
    await view.getByRole("button", { name: "Open selections, 2 open, 0 in history" }).click();
    await expect(
      view.getByRole("button", { name: /^(Activate|Current) selection S2[, ]/ }),
    ).not.toHaveAttribute("aria-label", /target unavailable/);
    await testInfo.attach("lens-layout-and-data", {
      body: await page.screenshot(),
      contentType: "image/png",
    });
    await view.getByRole("button", { name: "Close selections" }).click();
    if (mount === "anonymous") {
      expect((await inspect(view, "Resolve")).references.selections).toEqual([]);
      await view.getByRole("button", { name: "Open selections, 0 open, 2 in history" }).click();
      await view.getByRole("tab", { name: /History/ }).click();
      await view.getByRole("button", { name: "Reopen S2", exact: true }).click();
      await view.getByRole("button", { name: "Close selections" }).click();
      expect((await capturedContext(view, 1)).references.selections).toMatchObject([
        { note: "Make this heading clearer", target: { sources: [] }, cells: [] },
      ]);
    }
    if (mount === "notebook") {
      const scale = labeledSlider(view.locator('marimo-cell[name="controls"]'), /^Scale/);
      await scale.focus();
      await scale.press("ArrowRight");
      await expect(view.locator("#scalar")).toHaveText("84");
      await expect.poll(async () => (await inspect(view)).references.selections).toEqual([]);
      await select(view, view.locator("#scalar"), "Replacement Lens");
      expect((await inspect(view)).references.selections).toMatchObject([
        { note: "Replacement Lens" },
      ]);
      await expect(view.locator("[data-marimo-lens-view-conflict]")).toHaveCount(0);
    }
  });
}

test("Default Lens groups unannotated view HTML while preserving the clicked child", async ({
  page,
  studioCli,
}) => {
  const view = await openView(page, studioCli, "vanilla", "anonymous");
  await select(view, view.locator("#detail"), "Explain this phrase");
  const result = await capturedContext(view, 1);
  expect(result.references.selections).toMatchObject([
    {
      note: "Explain this phrase",
      target: { domSelector: "#layout", sources: [] },
      cells: [],
      domHint: { tag: "em", text: "this small phrase", path: "p > em" },
    },
  ]);
  const source = workspaceCreatedViewHtmlPath("lens");
  await writeWorkspaceFile(
    source,
    (await readFile(source, "utf8")).replace(
      'id="app-shell"',
      'id="app-shell" data-marimo-lens-scope="p"',
    ),
  );
  await studioCli.buildWorkspaceView("lens");
  await expect(view.locator("#app-shell")).toHaveAttribute("data-marimo-lens-scope", "p");
  await select(view, view.locator("#detail"), "A paragraph in this view");
  const changed = await capturedContext(view, 2);
  expect(changed.references.selections[1]?.target.domSelector).not.toBe("#layout");
  expect(changed.references.selections[1]?.domHint).toMatchObject({ tag: "em", path: "em" });
});

async function select(view: FrameLocator, target: Locator, note: string) {
  await target.scrollIntoViewIfNeeded();
  await view.getByRole("button", { name: "Select a target", exact: true }).click();
  await target.hover();
  const label = view.locator("[data-marimo-lens-target-label]");
  await expect(label).toBeVisible();
  const text = await label.innerText();
  await target.click();
  const dialog = view.getByRole("dialog", { name: /Add note for/ });
  await dialog.getByRole("textbox").fill(note);
  await dialog.getByRole("button", { name: "Done", exact: true }).click();
  await expect(dialog).toBeHidden();
  return text;
}

async function inspect(view: FrameLocator, action = "Inspect") {
  const report = view.locator("#lens-context");
  const previous = (await report.count()) ? await report.textContent() : null;
  const control = view.getByRole("combobox", { name: "Lens action" });
  const changed = (await control.locator("option:checked").textContent()) !== action;
  await control.selectOption({ label: action });
  if (changed) await expect(report).toHaveCount(0);
  await view.getByRole("button", { name: "Run Lens action", exact: true }).click();
  await expect(report).not.toHaveText(previous ?? "");
  return contextSchema.parse(JSON.parse(await report.innerText()));
}

async function capturedContext(view: FrameLocator, count: number) {
  let result!: z.infer<typeof contextSchema>;
  await expect
    .poll(async () => {
      result = await inspect(view);
      return result.references.selections.map((selection) => selection.snapshot.status);
    })
    .toEqual(Array.from({ length: count }, () => "available"));
  return result;
}

test("Lens captures native Studio values, rich outputs, and cells with producing context", async ({
  page,
  studioCli,
}) => {
  const view = await openView(page, studioCli, "vanilla");
  await expect(view.locator("#scalar")).toHaveText("42");
  expect(await select(view, view.locator("#scalar"), "Scalar value")).toContain("metrics.revenue");
  await select(view, view.locator("#rich"), "Rich value");
  await select(view, view.locator("#cell"), "Native cell");
  const result = await capturedContext(view, 3);
  expect(result.references.selections[0]?.description).toMatchObject({
    label: "metrics.revenue",
    renderSource: { path: "index.html" },
  });
  expect(
    result.references.selections.map((item) =>
      item.target.sources.map((source) => source.selector),
    ),
  ).toEqual([["metrics.revenue"], ["rich"], [null]]);
  for (const selection of result.references.selections) {
    expect(selection.cells).toEqual(
      selection.target.sources.map((source) => ({ id: source.cellId, status: "available" })),
    );
    expect(result.images[selection.id]).toBe("89504e470d0a1a0a");
  }
  const scale = labeledSlider(view.locator('marimo-cell[name="controls"]'), /^Scale/);
  await scale.focus();
  await scale.press("ArrowRight");
  await expect(view.locator("#scalar")).toHaveText("84");
  await expect(view.locator("#rich")).toContainText("Revenue report: 84");
  await expect(view.locator("#cell")).toContainText("Notebook total: 84");
  const source = workspaceCreatedViewHtmlPath("lens");
  await writeWorkspaceFile(
    source,
    (await readFile(source, "utf8")).replace(
      'id="scalar"',
      'id="scalar" data-marimo-lens-label="Revenue"',
    ),
  );
  await studioCli.buildWorkspaceView("lens");
  await expect(view.locator("#scalar")).toHaveAttribute("data-marimo-lens-label", "Revenue");
  await expect(view.locator("#scalar")).toHaveText("84");
  expect((await inspect(view)).references.selections[0]?.description?.label).toBe(
    "metrics.revenue",
  );

  expect((await inspect(view, "Resolve")).references.selections).toEqual([]);
  await view.getByRole("button", { name: "Open selections, 0 open, 3 in history" }).click();
  await view.getByRole("tab", { name: /History/ }).click();
  await view.getByRole("button", { name: "Reopen S1", exact: true }).click();
  await view.getByRole("button", { name: "Close selections" }).click();
  await expect
    .poll(async () => (await inspect(view)).references.selections)
    .toMatchObject([
      { target: result.references.selections[0]!.target, snapshot: { status: "available" } },
    ]);
});

for (const provider of ["react", "svelte"] as const) {
  test(`Lens preserves ${provider} metric provenance through rebinding and restoration`, async ({
    page,
    studioCli,
  }, testInfo) => {
    const view = await openView(page, studioCli, provider);
    const metric = view.locator("#metric");
    await expect(metric).toContainText("$42");
    const label = await select(view, metric, "Revenue metric");
    expect(label).toContain("Current metric");
    expect(label).toContain("metrics.revenue");
    await select(view, view.locator("#cost"), "Cost metric");
    const initial = await capturedContext(view, 2);
    const [revenue, cost] = initial.references.selections;
    expect(revenue?.description).toMatchObject({
      label: "Current metric",
      renderSource: {
        path: provider === "react" ? "src/App.tsx" : "src/App.svelte",
        symbol: "metricCard",
      },
    });
    expect(revenue?.target.sources).toEqual([
      { cellId: cost!.target.sources[0]!.cellId, selector: "metrics.revenue" },
    ]);
    expect(cost?.target.sources[0]?.selector).toBe("metrics.cost");

    await view.getByRole("button", { name: "Change metric", exact: true }).click();
    await expect(metric).toContainText("$12");
    await view.getByRole("button", { name: "Open selections, 2 open, 0 in history" }).click();
    await expect(
      view.getByRole("button", { name: /^Activate selection S1,.*target unavailable/ }),
    ).toBeVisible();
    await view.getByRole("button", { name: "Close selections" }).click();
    await view.getByRole("button", { name: "Change metric", exact: true }).click();
    await expect(metric).toContainText("$42");

    await view.getByRole("button", { name: "Open selections, 2 open, 0 in history" }).click();
    await expect(view.getByRole("button", { name: /^Activate selection S1,/ })).not.toHaveAttribute(
      "aria-label",
      /target unavailable/,
    );
    await view.getByRole("button", { name: "Close selections" }).click();

    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("combobox", { name: "Visible surface" }).selectOption("preview");
    await metric.scrollIntoViewIfNeeded();
    await view.getByRole("button", { name: "Select a target", exact: true }).click();
    await metric.hover();
    const indicator = view.locator("[data-marimo-lens-target-label]");
    await expect(indicator).toBeVisible();
    expect(
      await indicator.evaluate((element) => {
        const rect = element.getBoundingClientRect();
        return (
          rect.left >= 0 && rect.top >= 0 && rect.right <= innerWidth && rect.bottom <= innerHeight
        );
      }),
    ).toBe(true);
    await testInfo.attach("lens-metric", {
      body: await page.screenshot(),
      contentType: "image/png",
    });
  });
}
