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
        target: z.object({
          kind: z.literal("dom"),
          sources: z.array(z.object({ cellId: z.string(), selector: z.string().nullable() })),
        }),
        cells: z.array(z.object({ id: z.string(), status: z.string() })),
        snapshot: z.object({ status: z.string() }),
      }),
    ),
  }),
  images: z.record(z.string(), z.string()),
});

async function openView(page: Page, cli: StudioCli, provider: "vanilla" | "react" | "svelte") {
  const fixtures = resolve(fixtureDirectory, "lens");
  await rm(resolve(workspaceDirectory, "__marimo__/studio/notebook"), {
    recursive: true,
    force: true,
  });
  await writeWorkspaceFile(
    workspaceNotebookPath,
    await readFile(resolve(fixtures, "notebook.py.txt"), "utf8"),
  );
  await cli.addWorkspaceView(workspaceNotebookPath, "lens", `marimo-studio/${provider}:default`);
  const source = { vanilla: "index.html", react: "App.tsx", svelte: "App.svelte" }[provider];
  const destination = provider === "vanilla" ? source : `src/${source}`;
  await writeWorkspaceFile(
    resolve(workspaceDirectory, "__marimo__/studio/notebook/lens", destination),
    await readFile(resolve(fixtures, provider === "vanilla" ? source : `${source}.txt`), "utf8"),
  );
  await cli.buildWorkspaceView("lens");
  await page.goto("/studio/lens/?file=notebook.py");
  const view = await waitForViewPreview(page, "lens", "server", 120_000);
  await expect(view.getByRole("button", { name: "Select a target", exact: true })).toHaveCount(1);
  return view;
}

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
  await view.getByRole("combobox", { name: "Lens action" }).selectOption({ label: action });
  await view.getByRole("button", { name: "Run Lens action", exact: true }).click();
  await expect(report).not.toHaveText(previous ?? "");
  return contextSchema.parse(JSON.parse(await report.innerText()));
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
  await expect
    .poll(async () =>
      (await inspect(view)).references.selections.map((item) => item.snapshot.status),
    )
    .toEqual(["available", "available", "available"]);
  const result = await inspect(view);
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
    await expect(view.locator("#metric-source")).toBeHidden();
    const label = await select(view, metric, "Revenue metric");
    expect(label).toContain("Current metric");
    expect(label).toContain("metrics.revenue");
    await select(view, view.locator("#cost"), "Cost metric");
    await expect
      .poll(async () =>
        (await inspect(view)).references.selections.map((item) => item.snapshot.status),
      )
      .toEqual(["available", "available"]);
    const initial = await inspect(view);
    const [revenue, cost] = initial.references.selections;
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
    await page
      .getByRole("navigation", { name: "Studio surface" })
      .getByRole("button", { name: "Preview", exact: true })
      .click();
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
