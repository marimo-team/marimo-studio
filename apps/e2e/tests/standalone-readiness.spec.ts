import type { Page, Route } from "@playwright/test";

import { rm } from "node:fs/promises";

import type { ServerHandle } from "../scripts/server-process.ts";

import { e2eNetwork } from "../scripts/network.ts";
import {
  childLifecycleId,
  dashboardHtmlPath,
  dashboardManifestPath,
  expect,
  mirroredStates,
  presentationFrame,
  readWorkspaceFile,
  recordViewStateReports,
  recoverRequestAbort,
  recoverResponseTransition,
  studioEntryUrl,
  studioOrigin,
  test,
  viewStateReports,
  waitForPreview,
  workspaceCreatedViewHtmlPath,
  workspaceNotebookPath,
  writeWorkspaceFile,
} from "./fixture.ts";
import { startNotebookServer } from "./notebook-server.ts";
import { runServerToken, runServerUrl, startRunServer } from "./recovery-support.ts";

const closeAll = async (page: Page, server: ServerHandle) => {
  try {
    await page.close();
  } finally {
    await server.close();
  }
};

const standaloneUrl = () => `${runServerUrl()}/dashboard/?access_token=${runServerToken}`;

const expectTopLevelReady = async (page: Page, timeout = 65_000) => {
  await expect(page.locator("html")).toHaveAttribute("data-marimo-studio-state", "ready", {
    timeout,
  });
};

const frameRevision = (page: Page) =>
  presentationFrame(page).locator("html").getAttribute("data-marimo-studio-revision");

const preserveSession = async () => {
  const notebook = await readWorkspaceFile(workspaceNotebookPath);
  await writeWorkspaceFile(
    workspaceNotebookPath,
    notebook.replace("# preserve_session = false", "# preserve_session = true"),
  );
};

const appendToDashboard = async (markup: string) => {
  const dashboard = await readWorkspaceFile(dashboardHtmlPath);
  await writeWorkspaceFile(dashboardHtmlPath, dashboard.replace("</main>", `${markup}</main>`));
};

test("mirrors the view's readiness and revision on the top-level document", async ({ page }) => {
  const server = startRunServer();
  try {
    await server.waitUntilReady(standaloneUrl());
    await page.goto(standaloneUrl());

    await expectTopLevelReady(page);

    const revision = await page.locator("html").getAttribute("data-marimo-studio-revision");
    expect(revision).toBeTruthy();
    expect(revision).toBe(await frameRevision(page));
    expect(await page.evaluate(() => globalThis.marimoStudio.diagnostics())).toEqual([]);
  } finally {
    await closeAll(page, server);
  }
});

test("gives the view its public address inside the frame", async ({ page }) => {
  const server = startRunServer();
  try {
    await server.waitUntilReady(standaloneUrl());
    await page.goto(`${standaloneUrl()}&region=emea`);
    await expectTopLevelReady(page);
    const frameDocument = presentationFrame(page).locator("html");

    const announced = await frameDocument.evaluate(
      () =>
        new Promise<string>((resolve) => {
          addEventListener("message", (event: MessageEvent<{ type?: string; url: string }>) => {
            if (event.data.type === "marimo-studio:public-url") {
              resolve(event.data.url);
            }
          });
          const target = new URL(location.href);
          target.searchParams.set("tab", "map");
          target.hash = "#details";
          history.replaceState(null, "", target);
        }),
    );

    const expected = `${runServerUrl()}/dashboard/?region=emea&tab=map#details`;
    expect(announced).toBe(expected);
    await expect(page).toHaveURL(expected);
    const publicUrl = await frameDocument.evaluate(() => globalThis.marimoStudio.publicUrl());
    expect(publicUrl).toBe(expected);
    for (const secret of ["session_id", "access_token", "marimo_studio", "_marimo-studio"]) {
      expect(publicUrl).not.toContain(secret);
    }
  } finally {
    await closeAll(page, server);
  }
});

test("surfaces a runtime failure and its diagnostic at the top level", async ({
  browserDiagnostics,
  page,
}) => {
  const rejected = browserDiagnostics.expectConsole({
    type: "error",
    text: /marimo-studio runtime error/,
  });
  const responseLog = browserDiagnostics.expectConsole({
    type: "error",
    text: /Failed to load resource: the server responded with a status of 403/,
    required: false,
  });
  await page.route("**/_marimo-studio/views/dashboard/config**", (route) =>
    route.fulfill({
      status: 403,
      contentType: "application/json",
      body: JSON.stringify({
        error: "runtime-config-forbidden",
        message: "This view is unavailable to this page.",
        hint: "Reopen the view from its public address.",
      }),
    }),
  );
  const refused = browserDiagnostics.expectResponse({
    path: /\/_marimo-studio\/views\/dashboard\/config$/,
    status: 403,
  });
  const server = startRunServer();
  try {
    await server.waitUntilReady(standaloneUrl());
    await page.goto(standaloneUrl());

    await expect(page.locator("html")).toHaveAttribute("data-marimo-studio-state", "error", {
      timeout: 65_000,
    });
    await expect
      .poll(() => page.evaluate(() => globalThis.marimoStudio.diagnostics()))
      .toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            severity: "error",
            message: expect.stringMatching(/unavailable to this page/),
          }),
        ]),
      );
    rejected.recovered();
    responseLog.recovered();
    refused.recovered();
  } finally {
    await closeAll(page, server);
  }
});

test("reports loading through an in-place view switch", async ({
  browserDiagnostics,
  page,
  studioCli,
}) => {
  await preserveSession();
  await studioCli.addWorkspaceView(workspaceNotebookPath, "report");
  await appendToDashboard(`<nav><a href="../report/">Report</a></nav>`);
  await writeWorkspaceFile(
    workspaceCreatedViewHtmlPath("report"),
    `<!doctype html><html lang="en"><head><title>Report</title></head><body><main id="app-shell"><h1>Report</h1></main></body></html>`,
  );
  await recordViewStateReports(page);
  const server = startRunServer();
  try {
    await server.waitUntilReady(standaloneUrl());
    await page.goto(standaloneUrl());
    await expectTopLevelReady(page);
    const dashboardRevision = await frameRevision(page);
    const documentLifecycle = await childLifecycleId(page);
    const statesBefore = (await mirroredStates(page)).length;
    const replaced = browserDiagnostics.expectActiveRequestAbort({
      origin: runServerUrl(),
      method: "GET",
      path: /^\/_marimo-studio\/presentation\/d\.[^/]+\/dashboard\/$/,
      required: false,
    });

    await presentationFrame(page).getByRole("link", { name: "Report", exact: true }).click();
    await expect(page).toHaveURL(/\/report\//);
    await expect(presentationFrame(page).getByRole("heading", { name: "Report" })).toBeVisible();
    await expectTopLevelReady(page);

    expect((await mirroredStates(page)).slice(statesBefore)).toEqual(["loading", "ready"]);
    expect(await childLifecycleId(page)).toBe(documentLifecycle);
    const revision = await page.locator("html").getAttribute("data-marimo-studio-revision");
    expect(revision).not.toBe(dashboardRevision);
    expect(revision).toBe(await frameRevision(page));
    await recoverRequestAbort(replaced);
  } finally {
    await closeAll(page, server);
  }
});

test("a replaced document cannot mark the frame's next document ready", async ({
  context,
  page,
}) => {
  await page.goto(studioEntryUrl);
  await waitForPreview(page);
  const standalone = await context.newPage();
  await recordViewStateReports(standalone);
  try {
    await standalone.goto(`${studioOrigin()}/dashboard/?file=notebook.py`);
    await expectTopLevelReady(standalone);
    const firstLifecycle = await childLifecycleId(standalone);

    let release = () => {};
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const holdConfig = async (route: Route) => {
      await held;
      await route.continue();
    };
    await standalone.route("**/_marimo-studio/views/dashboard/config**", holdConfig);

    await presentationFrame(standalone)
      .locator("html")
      .evaluate(() => {
        setTimeout(() => globalThis.location.reload(), 0);
      });

    await expect(standalone.locator("html")).not.toHaveAttribute(
      "data-marimo-studio-state",
      "ready",
    );
    await expect
      .poll(async () => {
        const lifecycle = (await viewStateReports(standalone)).at(-1)?.lifecycleId;
        return lifecycle !== firstLifecycle ? lifecycle : undefined;
      })
      .toBeTruthy();
    const nextLifecycle = (await viewStateReports(standalone)).at(-1)?.lifecycleId;

    // Reports from one source arrive in order, so the location change marks
    // the point where the stale report has already reached the wrapper.
    await presentationFrame(standalone)
      .locator("html")
      .evaluate(
        (_root, { stale, current }) => {
          globalThis.parent.postMessage(
            {
              type: "marimo-studio:view-state",
              runtime: "server",
              lifecycleId: stale,
              state: "ready",
              revision: "stale-revision",
              diagnostics: [],
            },
            "*",
          );
          globalThis.parent.postMessage(
            {
              type: "marimo-studio:location-change",
              runtime: "server",
              lifecycleId: current,
              query: "?barrier=1",
              hash: "",
            },
            "*",
          );
        },
        { stale: firstLifecycle, current: nextLifecycle },
      );
    await expect(standalone).toHaveURL(/barrier=1/);
    await expect(standalone.locator("html")).not.toHaveAttribute(
      "data-marimo-studio-state",
      "ready",
    );

    release();
    await expectTopLevelReady(standalone);
    expect(await standalone.locator("html").getAttribute("data-marimo-studio-revision")).toBe(
      await frameRevision(standalone),
    );
    await standalone.unroute("**/_marimo-studio/views/dashboard/config**", holdConfig);
  } finally {
    await standalone.close();
  }
});

test("keyboard input reaches the view without a click", async ({ page }) => {
  await appendToDashboard(
    `<output id="keys"></output>
     <script type="module">
       addEventListener("keydown", (event) => {
         document.querySelector("#keys").textContent += event.key;
       });
     </script>`,
  );
  const server = startRunServer();
  try {
    await server.waitUntilReady(standaloneUrl());
    await page.goto(standaloneUrl());
    await expectTopLevelReady(page);

    await page.keyboard.press("j");

    await expect(presentationFrame(page).locator("#keys")).toHaveText("j");
    expect(await page.evaluate(() => document.activeElement?.id)).toBe(
      "marimo-studio-presentation",
    );
  } finally {
    await closeAll(page, server);
  }
});

test("leaves focus on an element the visitor is using", async ({ page }) => {
  await page.addInitScript(() => {
    if (globalThis.top !== globalThis.self) {
      return;
    }
    globalThis.addEventListener("DOMContentLoaded", () => {
      const input = document.createElement("input");
      input.id = "visitor-input";
      document.body.prepend(input);
      input.focus();
    });
  });
  const server = startRunServer();
  try {
    await server.waitUntilReady(standaloneUrl());
    await page.goto(standaloneUrl());
    await expectTopLevelReady(page);

    expect(await page.evaluate(() => document.activeElement?.id)).toBe("visitor-input");
  } finally {
    await closeAll(page, server);
  }
});

test("an embedded wrapper leaves readiness and focus to its host", async ({
  browserDiagnostics,
  page,
}) => {
  const framePolicyNotices = browserDiagnostics.expectConsole({
    text: /\[iframe\] (Clipboard|Media devices) API unavailable/,
    required: false,
  });
  const server = startNotebookServer({
    command: "run",
    target: workspaceNotebookPath,
    endpoint: e2eNetwork.main.recovery,
    authentication: ["--no-token"],
  });
  await page.addInitScript(() => {
    if (globalThis.top !== globalThis.self) {
      return;
    }
    globalThis.addEventListener("message", (event: MessageEvent) => {
      const host = document.querySelector<HTMLIFrameElement>("#host-frame");
      if (event.source === host?.contentWindow && event.data?.type === "marimo-studio:view-ready") {
        document.documentElement.dataset.embeddedViewReady = "";
      }
    });
  });
  try {
    await server.waitUntilReady(`${runServerUrl()}/dashboard/`);
    await page.goto(`${runServerUrl()}/dashboard/`);
    await expectTopLevelReady(page);
    await page.evaluate(() => {
      const host = document.createElement("iframe");
      host.id = "host-frame";
      host.src = location.href;
      document.body.append(host);
    });
    const wrapper = page.frameLocator("#host-frame");
    await expect(
      wrapper.frameLocator("iframe#marimo-studio-presentation").locator("html"),
    ).toHaveAttribute("data-marimo-studio-state", "ready", { timeout: 65_000 });

    // The frame reports state before ready, and the wrapper relays ready after
    // handling both, so this marks the point where the state was already seen.
    await expect(page.locator("html")).toHaveAttribute("data-embedded-view-ready", "");
    await expect(wrapper.locator("html")).not.toHaveAttribute("data-marimo-studio-state");
    expect(
      await wrapper.locator("html").evaluate(() => document.activeElement === document.body),
    ).toBe(true);
    framePolicyNotices.recovered();
  } finally {
    await closeAll(page, server);
  }
});

test("a failed build stays ready and reports its error at the top level", async ({
  browserDiagnostics,
  context,
  page,
}) => {
  const buildErrors = browserDiagnostics.expectConsole({
    type: "error",
    text: /marimo-studio build error/,
    required: false,
  });
  await page.goto(studioEntryUrl);
  await waitForPreview(page);
  const standalone = await context.newPage();
  try {
    await standalone.goto(`${studioOrigin()}/dashboard/?file=notebook.py`);
    await expectTopLevelReady(standalone);
    const revision = await standalone.locator("html").getAttribute("data-marimo-studio-revision");
    expect(revision).toBeTruthy();

    await rm(dashboardHtmlPath);

    await expect
      .poll(() => standalone.evaluate(() => globalThis.marimoStudio.diagnostics()), {
        timeout: 30_000,
      })
      .toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            severity: "error",
            message: expect.stringMatching(/^Latest build failed/),
          }),
        ]),
      );
    await expectTopLevelReady(standalone);
    expect(await standalone.locator("html").getAttribute("data-marimo-studio-revision")).toBe(
      revision,
    );
    buildErrors.recovered();
  } finally {
    await standalone.close();
  }
});

test("a repair page in the frame reports its error at the top level", async ({
  browserDiagnostics,
  context,
  page,
}) => {
  const manifest = await readWorkspaceFile(dashboardManifestPath);
  await page.goto(studioEntryUrl);
  await waitForPreview(page);
  const standalone = await context.newPage();
  const projectRepair = browserDiagnostics.expectResponseTransition(page, {
    origin: studioOrigin(),
    method: "GET",
    path: /^\/_marimo-studio\/views\/dashboard\/project$/,
    failureStatus: 500,
    failureError: "configuration-error",
    successStatus: 200,
  });
  const readProject = () =>
    page.evaluate(async () => {
      const response = await fetch("/_marimo-studio/views/dashboard/project?file=notebook.py");
      return { status: response.status, body: await response.json() };
    });
  try {
    await standalone.goto(`${studioOrigin()}/dashboard/?file=notebook.py`);
    await expectTopLevelReady(standalone);
    const refused = browserDiagnostics.expectResponse({
      path: /\/dashboard\/$/,
      status: 500,
      required: false,
    });
    await writeWorkspaceFile(dashboardManifestPath, "schema = 'broken'\n");
    // Exercise the open editor's refresh while the manifest is invalid.
    expect(await readProject()).toMatchObject({
      status: 500,
      body: { error: "configuration-error" },
    });

    await presentationFrame(standalone)
      .locator("html")
      .evaluate(() => {
        setTimeout(() => globalThis.location.reload(), 0);
      });

    await expect(standalone.locator("html")).toHaveAttribute("data-marimo-studio-state", "error", {
      timeout: 30_000,
    });
    expect(await standalone.evaluate(() => globalThis.marimoStudio.diagnostics())).toEqual([
      expect.objectContaining({ severity: "error", view: expect.any(String) }),
    ]);
    await writeWorkspaceFile(dashboardManifestPath, manifest);
    projectRepair.seal();
    await waitForPreview(page);
    expect((await readProject()).status).toBe(200);
    await recoverResponseTransition(projectRepair);
    refused.recovered();
  } finally {
    await writeWorkspaceFile(dashboardManifestPath, manifest);
    await standalone.close();
  }
});

test("a top-level repair page exposes its diagnostic", async ({ browserDiagnostics, page }) => {
  const manifest = await readWorkspaceFile(dashboardManifestPath);
  await writeWorkspaceFile(dashboardManifestPath, "schema = 'broken'\n");
  const refused = browserDiagnostics.expectResponse({
    path: /\/dashboard\/$/,
    status: 500,
    required: false,
  });
  try {
    await page.goto(`${studioOrigin()}/dashboard/?file=notebook.py`);

    await expect(page.locator("html")).toHaveAttribute("data-marimo-studio-state", "error");
    expect(await page.evaluate(() => globalThis.marimoStudio.diagnostics())).toEqual([
      expect.objectContaining({ severity: "error" }),
    ]);
    refused.recovered();
  } finally {
    await writeWorkspaceFile(dashboardManifestPath, manifest);
  }
});
