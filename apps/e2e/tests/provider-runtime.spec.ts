import { mountConfigSchema } from "@marimo-studio/protocol/runtime-config";
import { expect, test, type Locator, type Page } from "@playwright/test";

import { e2eNetwork } from "../scripts/network.mjs";
import { observeBrowserContext } from "./browser-diagnostics.ts";
import { labeledSlider, presentationFrame, WASM_PREVIEW_TIMEOUT } from "./fixture.ts";
import { installPinnedPyodideAssets } from "./pyodide-assets.ts";

const cases = [
  {
    framework: "React",
    heading: "Gallery",
    liveUrl: `${e2eNetwork.provider.live.origin}/gallery/`,
    staticUrl: `${e2eNetwork.provider.gallery.origin}/`,
  },
  {
    framework: "Svelte",
    heading: "Story",
    liveUrl: `${e2eNetwork.provider.live.origin}/story/`,
    staticUrl: `${e2eNetwork.provider.story.origin}/`,
  },
] as const;

const readNativeTableLayout = async (root: Locator) =>
  root.evaluate(() => {
    const output = document.querySelector<HTMLElement>('marimo-cell[name="records"]');
    const tableElement = output?.querySelector<HTMLElement>("marimo-table");
    const shadow = tableElement?.shadowRoot;
    const search = shadow?.querySelector<HTMLInputElement>('input[placeholder="Search..."]');
    const toolbar = search?.parentElement?.parentElement;
    const table = shadow?.querySelector<HTMLTableElement>("table");
    const scrollOwner = table?.parentElement;
    if (!output || !shadow || !search || !toolbar || !table || !scrollOwner) {
      throw new Error("The projected native table layout is incomplete");
    }

    const outputRect = output.getBoundingClientRect();
    const toolbarRect = toolbar.getBoundingClientRect();
    const tableRect = scrollOwner.getBoundingClientRect();
    const searchRect = search.getBoundingClientRect();
    const actionNames = ["Columns", "Explore", "Export"];
    const actions = actionNames.map((name) => {
      const button = Array.from(shadow.querySelectorAll("button")).find(
        (candidate) => candidate.textContent?.trim() === name,
      );
      if (!button) {
        throw new Error(`The native table ${name} control is unavailable`);
      }
      const rect = button.getBoundingClientRect();
      return {
        disabled: button.disabled,
        height: rect.height,
        left: rect.left,
        name,
        right: rect.right,
        top: rect.top,
        width: rect.width,
      };
    });
    const previousScrollLeft = scrollOwner.scrollLeft;
    scrollOwner.scrollLeft = previousScrollLeft === 0 ? 1 : 0;
    const tableScrollsInsidePage = scrollOwner.scrollLeft !== previousScrollLeft;
    scrollOwner.scrollLeft = previousScrollLeft;

    return {
      actionNames: actions.map(({ name }) => name),
      actionsEnabled: actions.every(({ disabled }) => !disabled),
      actionsShareRow: new Set(actions.map(({ top }) => Math.round(top))).size === 1,
      actionsWithinToolbar: actions.every(
        ({ left, right }) => left >= toolbarRect.left && right <= toolbarRect.right,
      ),
      controlsVisible:
        searchRect.width > 0 &&
        searchRect.height > 0 &&
        actions.every(({ height, width }) => height > 0 && width > 0),
      tableHasContent: (table.tBodies[0]?.rows.length ?? 0) > 0 && tableRect.height > 0,
      tableWithinOutput: tableRect.left >= outputRect.left && tableRect.right <= outputRect.right,
      tableScrollsInsidePage,
      viewportHasNoHorizontalOverflow:
        document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    };
  });

const expectNativeTableLayout = async (root: Locator, requireInnerScroll = false) => {
  const layout = await readNativeTableLayout(root);
  expect(layout.actionNames).toEqual(["Columns", "Explore", "Export"]);
  expect(layout.actionsEnabled).toBe(true);
  expect(layout.actionsShareRow).toBe(true);
  expect(layout.actionsWithinToolbar).toBe(true);
  expect(layout.controlsVisible).toBe(true);
  expect(layout.tableHasContent).toBe(true);
  expect(layout.tableWithinOutput).toBe(true);
  if (requireInnerScroll) {
    expect(layout.tableScrollsInsidePage).toBe(true);
  }
  expect(layout.viewportHasNoHorizontalOverflow).toBe(true);
};

const waitForRuntime = async (root: Locator, timeout = 65_000): Promise<void> => {
  const deadline = Date.now() + timeout;
  const remaining = () => Math.max(1, deadline - Date.now());
  await expect
    .poll(() => root.evaluate(() => globalThis.marimoStudio !== undefined).catch(() => false), {
      timeout: remaining(),
    })
    .toBe(true);
  await root.evaluate(
    (_root, readyTimeout) =>
      Promise.race([
        globalThis.marimoStudio.ready(),
        new Promise<never>((_resolve, reject) =>
          setTimeout(
            () => reject(new Error("The projection runtime did not become ready")),
            readyTimeout,
          ),
        ),
      ]),
    remaining(),
  );
};

const expectNotebookContent = async (root: Locator, heading: string): Promise<void> => {
  await expect(root.getByRole("heading", { name: heading, exact: true })).toBeVisible();
  await expect(labeledSlider(root.locator('marimo-cell[name="controls"]'), /^Scale/)).toBeVisible();
  await expect(root.locator('marimo-cell[name="metric"]')).toHaveText("42");
  await expect(
    root.locator('marimo-cell[name="records"]').getByRole("button", { name: "Columns" }),
  ).toBeVisible();
  await expect(root.getByRole("heading", { name: "First projected result" })).toBeVisible();
  await expect(root.getByRole("heading", { name: "Second projected result" })).toBeVisible();
};

const exerciseRuntime = async (
  page: Page,
  url: string,
  heading: string,
  runtimeLabel: "Server" | "static WebAssembly",
) => {
  const diagnostics = observeBrowserContext(page.context());
  const initialNavigation = await page.goto(url);
  const initialStatus = initialNavigation?.status();
  if (initialStatus === 409) {
    expect(initialNavigation?.headers()["marimo-studio-error"]).toBe("runtime-sync-pending");
    expect(initialNavigation?.headers()["marimo-studio-transient"]).toBe("true");
  } else {
    expect(initialStatus).toBeGreaterThanOrEqual(200);
    expect(initialStatus).toBeLessThan(400);
  }

  const root =
    runtimeLabel === "Server" ? presentationFrame(page).locator("html") : page.locator("html");
  await waitForRuntime(root, runtimeLabel === "static WebAssembly" ? WASM_PREVIEW_TIMEOUT : 65_000);
  const mount = mountConfigSchema.parse(
    await root.evaluate(() => globalThis.__MARIMO_MOUNT_CONFIG__),
  );
  expect(mount.runtime).toBe(runtimeLabel === "Server" ? "server" : "wasm");
  await expectNotebookContent(root, heading);
  await diagnostics.close();
  expect(diagnostics.messages).toEqual([]);
};

test("Vanilla renders populated notebook cells and a responsive native table", async ({ page }) => {
  const diagnostics = observeBrowserContext(page.context());
  await page.setViewportSize({ width: 1_280, height: 900 });
  await page.goto(`${e2eNetwork.provider.live.origin}/overview/`);
  const root = presentationFrame(page).locator("html");
  await waitForRuntime(root);
  await expectNotebookContent(root, "Overview");
  await expectNativeTableLayout(root);
  await page.setViewportSize({ width: 420, height: 900 });
  await expectNativeTableLayout(root, true);
  await diagnostics.close();
  expect(diagnostics.messages).toEqual([]);
});

test.describe("built-in framework projection runtimes", () => {
  test.setTimeout(300_000);

  for (const candidate of cases) {
    test(`${candidate.framework} renders the same notebook cells on Server and static WebAssembly`, async ({
      browser,
    }) => {
      const context = await browser.newContext();
      try {
        await installPinnedPyodideAssets(context);
        const serverPage = await context.newPage();
        await exerciseRuntime(serverPage, candidate.liveUrl, candidate.heading, "Server");
        await serverPage.close();

        const staticPage = await context.newPage();
        await exerciseRuntime(
          staticPage,
          candidate.staticUrl,
          candidate.heading,
          "static WebAssembly",
        );
        await staticPage.close();
      } finally {
        await context.close();
      }
    });
  }
});
