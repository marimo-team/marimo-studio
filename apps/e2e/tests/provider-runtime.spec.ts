import { mountConfigSchema } from "@marimo-studio/protocol/runtime-config";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { z } from "zod";

import type { ProviderProjection, ReadyCellProjection } from "./provider-runtime-evidence.ts";

import { e2eNetwork } from "../scripts/network.mjs";
import { observeBrowserContext } from "./browser-diagnostics.ts";
import { presentationFrame } from "./fixture.ts";
import {
  failedCellProjectionSchema,
  providerProjectionSchema,
  readyCellProjectionSchema,
} from "./provider-runtime-evidence.ts";
import { installPinnedPyodideAssets } from "./pyodide-assets.ts";

interface NgaProjectionAcceptance {
  readonly framework: "React" | "Svelte";
  readonly initial: string;
  readonly alternate: string;
  readonly siteId: string;
  retarget(target: string): void | Promise<void>;
  unmount(): void | Promise<void>;
  mount(target: string): void | Promise<void>;
}

declare global {
  var __ngaProjectionAcceptance: NgaProjectionAcceptance | undefined;
  var __ngaProjectionRuntimeMarker: string | undefined;
}

const bridgeSchema = z.strictObject({
  framework: z.enum(["React", "Svelte"]),
  initial: z.string().min(1),
  alternate: z.string().min(1),
  siteId: z.string().min(1),
});

const cases = [
  {
    framework: "React",
    liveUrl: `${e2eNetwork.provider.live.origin}/gallery/`,
    staticUrl: `${e2eNetwork.provider.gallery.origin}/`,
  },
  {
    framework: "Svelte",
    liveUrl: `${e2eNetwork.provider.live.origin}/story/`,
    staticUrl: `${e2eNetwork.provider.story.origin}/`,
  },
] as const;

const readSite = async (root: Locator, siteId: string): Promise<ProviderProjection[]> =>
  providerProjectionSchema
    .array()
    .parse(
      await root.evaluate(
        (_document, selectedSite) =>
          globalThis.marimoStudio
            .projections()
            .filter((projection) => projection.mountId === selectedSite),
        siteId,
      ),
    );

const waitForProjection = async (
  root: Locator,
  siteId: string,
  target: string,
  state: "ready" | "error",
): Promise<ProviderProjection> => {
  await expect
    .poll(
      async () =>
        (await readSite(root, siteId)).map((projection) => ({
          phase: projection.phase,
          target: projection.target,
        })),
      { timeout: 65_000 },
    )
    .toEqual([{ phase: state, target }]);
  const [projection] = await readSite(root, siteId);
  if (projection === undefined) {
    throw new Error("The dynamic projection host disappeared after becoming ready");
  }
  return projection;
};

const mutate = async (
  root: Locator,
  operation: "retarget" | "unmount" | "mount",
  target?: string,
): Promise<void> => {
  await root.evaluate(
    async (_document, { method, nextTarget }) => {
      const bridge = globalThis.__ngaProjectionAcceptance;
      if (bridge === undefined) {
        throw new Error("The NGA projection acceptance bridge is unavailable");
      }
      if (method === "unmount") {
        await bridge.unmount();
        return;
      }
      if (nextTarget === undefined) {
        throw new Error("Projection retargeting requires a target");
      }
      if (method === "retarget") {
        await bridge.retarget(nextTarget);
      } else {
        await bridge.mount(nextTarget);
      }
    },
    { method: operation, nextTarget: target },
  );
};

const symbolicIdentity = (projection: ReadyCellProjection) => ({
  mountId: projection.mountId,
  target: projection.target,
});

const readNativeTableLayout = async (root: Locator) =>
  root.evaluate(() => {
    const output = document.querySelector<HTMLElement>('marimo-output[value="artwork_totals_df"]');
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
        name,
        left: rect.left,
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
      viewportHasNoHorizontalOverflow:
        document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      tableScrollsInsidePage,
    };
  });

const expectNativeTableLayout = async (root: Locator) => {
  const layout = await readNativeTableLayout(root);
  expect(layout.actionNames).toEqual(["Columns", "Explore", "Export"]);
  expect(layout.actionsEnabled).toBe(true);
  expect(layout.actionsShareRow).toBe(true);
  expect(layout.actionsWithinToolbar).toBe(true);
  expect(layout.controlsVisible).toBe(true);
  expect(layout.tableHasContent).toBe(true);
  expect(layout.tableWithinOutput).toBe(true);
  expect(layout.tableScrollsInsidePage).toBe(true);
  expect(layout.viewportHasNoHorizontalOverflow).toBe(true);
};

interface LifecycleEvidence {
  readonly siteId: string;
  readonly initial: ReturnType<typeof symbolicIdentity>;
  readonly alternate: ReturnType<typeof symbolicIdentity>;
}

const exerciseLifecycle = async (
  page: Page,
  url: string,
  expectedFramework: "React" | "Svelte",
  runtimeLabel: "Server" | "static WebAssembly",
): Promise<LifecycleEvidence> => {
  const diagnostics = observeBrowserContext(page.context());

  await page.goto(url);
  const root =
    runtimeLabel === "Server" ? presentationFrame(page).locator("html") : page.locator("html");
  await test.step(`${expectedFramework} ${runtimeLabel} starts`, async () => {
    await expect
      .poll(
        () =>
          root
            .evaluate(
              () =>
                globalThis.__ngaProjectionAcceptance !== undefined &&
                globalThis.marimoStudio !== undefined,
            )
            .catch(() => false),
        { timeout: 65_000 },
      )
      .toBe(true);
    await root.evaluate(() =>
      Promise.race([
        globalThis.marimoStudio.ready(),
        new Promise<never>((_resolve, reject) =>
          setTimeout(
            () => reject(new Error("The projection runtime did not become ready")),
            65_000,
          ),
        ),
      ]),
    );
    const mount = mountConfigSchema.parse(
      await root.evaluate(() => globalThis.__MARIMO_MOUNT_CONFIG__),
    );
    expect(mount.runtime).toBe(runtimeLabel === "Server" ? "server" : "wasm");
  });
  const bridge = bridgeSchema.parse(
    await root.evaluate(() => {
      const acceptance = globalThis.__ngaProjectionAcceptance;
      if (acceptance === undefined) {
        throw new Error("The NGA projection acceptance bridge is unavailable");
      }
      return {
        framework: acceptance.framework,
        initial: acceptance.initial,
        alternate: acceptance.alternate,
        siteId: acceptance.siteId,
      };
    }),
  );
  expect(bridge.framework).toBe(expectedFramework);
  const marker = await root.evaluate(() => {
    globalThis.__ngaProjectionRuntimeMarker ??= crypto.randomUUID();
    return globalThis.__ngaProjectionRuntimeMarker;
  });

  const initial =
    await test.step(`${expectedFramework} ${runtimeLabel} initial projection`, async () =>
      readyCellProjectionSchema.parse(
        await waitForProjection(root, bridge.siteId, bridge.initial, "ready"),
      ));

  const alternate = await test.step(`${expectedFramework} ${runtimeLabel} retargets`, async () => {
    await mutate(root, "retarget", bridge.alternate);
    return readyCellProjectionSchema.parse(
      await waitForProjection(root, bridge.siteId, bridge.alternate, "ready"),
    );
  });
  expect(alternate.instanceId).toBe(initial.instanceId);
  expect(alternate.runtimeCellId).not.toBe(initial.runtimeCellId);

  const invalid =
    await test.step(`${expectedFramework} ${runtimeLabel} reports an invalid target`, async () => {
      await mutate(root, "retarget", "missing_cell");
      return failedCellProjectionSchema.parse(
        await waitForProjection(root, bridge.siteId, "missing_cell", "error"),
      );
    });
  expect(invalid.instanceId).toBe(initial.instanceId);
  expect(invalid.error.code).toMatch(/^projection-(?:cell-not-found|target-not-allowed)$/);

  const recovered = await test.step(`${expectedFramework} ${runtimeLabel} recovers`, async () => {
    await mutate(root, "retarget", bridge.initial);
    return readyCellProjectionSchema.parse(
      await waitForProjection(root, bridge.siteId, bridge.initial, "ready"),
    );
  });
  expect(recovered.instanceId).toBe(initial.instanceId);
  expect(symbolicIdentity(recovered)).toEqual(symbolicIdentity(initial));

  const remounted =
    await test.step(`${expectedFramework} ${runtimeLabel} unmounts and remounts`, async () => {
      await mutate(root, "unmount");
      await expect.poll(() => readSite(root, bridge.siteId)).toEqual([]);
      await mutate(root, "mount", bridge.initial);
      return readyCellProjectionSchema.parse(
        await waitForProjection(root, bridge.siteId, bridge.initial, "ready"),
      );
    });
  expect(remounted.instanceId).not.toBe(initial.instanceId);
  expect(symbolicIdentity(remounted)).toEqual(symbolicIdentity(initial));

  expect(await root.evaluate(() => globalThis.__ngaProjectionRuntimeMarker)).toBe(marker);
  expect(await root.evaluate(() => performance.getEntriesByType("navigation").length)).toBe(1);
  await diagnostics.close();
  expect(diagnostics.messages).toEqual([]);
  return {
    siteId: bridge.siteId,
    initial: symbolicIdentity(initial),
    alternate: symbolicIdentity(alternate),
  };
};

test("Vanilla overview starts with populated values and projections", async ({ page }) => {
  const diagnostics = observeBrowserContext(page.context());
  await page.setViewportSize({ width: 1_280, height: 900 });
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"], {
    origin: e2eNetwork.provider.live.origin,
  });

  await page.goto(`${e2eNetwork.provider.live.origin}/overview/`);
  const root = presentationFrame(page).locator("html");
  await expect
    .poll(() => root.evaluate(() => globalThis.marimoStudio !== undefined).catch(() => false), {
      timeout: 65_000,
    })
    .toBe(true);
  await root.evaluate(() =>
    Promise.race([
      globalThis.marimoStudio.ready(),
      new Promise<never>((_resolve, reject) =>
        setTimeout(() => reject(new Error("The Vanilla overview did not become ready")), 65_000),
      ),
    ]),
  );

  await expect(root.locator(".metrics strong")).toHaveText(["12", "4", "8", "12"]);
  await expect(root.locator("#copy-summary")).toBeEnabled();
  await expect(root.getByRole("cell", { name: "Artist 1", exact: true })).toBeVisible();
  await expectNativeTableLayout(root);
  await page.setViewportSize({ width: 420, height: 900 });
  await expectNativeTableLayout(root);
  await expect
    .poll(() =>
      root.evaluate(() =>
        globalThis.marimoStudio
          .projections()
          .map(({ phase, target }) => ({ phase, target }))
          .sort((first, second) => first.target.localeCompare(second.target)),
      ),
    )
    .toEqual(
      [
        "artist_totals_chart",
        "artwork_totals_df",
        "classification_bar_chart",
        "collection_timeline_chart",
        "studio_summary",
        "studio_summary.artists",
        "studio_summary.artworks",
        "studio_summary.index_drawings",
        "studio_summary.public_domain",
      ]
        .sort()
        .map((target) => ({ phase: "ready", target })),
    );

  await root.locator("#copy-summary").click();
  await expect(root.locator("#copy-status")).toHaveText("Summary copied");
  await expect(root.getByRole("link", { name: "Gallery", exact: true })).toHaveAttribute(
    "href",
    "../gallery/",
  );
  await expect(root.getByRole("link", { name: "Story", exact: true })).toHaveAttribute(
    "href",
    "../story/",
  );

  await diagnostics.close();
  expect(diagnostics.messages).toEqual([]);
});

test.describe("built-in framework projection runtimes", () => {
  test.setTimeout(180_000);

  for (const candidate of cases) {
    test(`${candidate.framework} preserves dynamic projections across Server and static WebAssembly`, async ({
      browser,
    }) => {
      const context = await browser.newContext();
      try {
        await installPinnedPyodideAssets(context);
        const serverPage = await context.newPage();
        const server = await exerciseLifecycle(
          serverPage,
          candidate.liveUrl,
          candidate.framework,
          "Server",
        );
        await serverPage.close();

        const staticPage = await context.newPage();
        const wasm = await exerciseLifecycle(
          staticPage,
          candidate.staticUrl,
          candidate.framework,
          "static WebAssembly",
        );
        await staticPage.close();

        expect(wasm).toEqual(server);
      } finally {
        await context.close();
      }
    });
  }
});
