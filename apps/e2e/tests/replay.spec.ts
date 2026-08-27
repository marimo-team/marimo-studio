import type { Page, Request, Route } from "@playwright/test";

import {
  expect,
  labeledSlider,
  presentationFrame,
  readWorkspaceFile,
  recoverRequestAbort,
  test,
  workspaceNotebookPath,
  writeWorkspaceFile,
} from "./fixture.ts";
import { stopNotebookServer, waitForNotebookServer } from "./notebook-server.ts";
import { runServerToken, runServerUrl, startRunServer } from "./recovery-support.ts";

test("preserves run-mode kernel state across a page reload", async ({ page }) => {
  const invalidReplayDocuments: string[] = [];
  const recordReplayDocument = (request: Request) => {
    const url = new URL(request.url());
    const sessionIds = url.searchParams.getAll("session_id");
    if (
      request.method() === "GET" &&
      request.resourceType() === "document" &&
      /^\/_marimo-studio\/presentation\/d\.[^/]+\/dashboard\/$/.test(url.pathname) &&
      url.searchParams.get("marimo_studio_resume") === "1" &&
      (sessionIds.length !== 1 || !/^s_[a-z0-9]{6}$/.test(sessionIds[0] ?? ""))
    ) {
      invalidReplayDocuments.push(url.href);
    }
  };
  page.on("request", recordReplayDocument);
  const source = await readWorkspaceFile(workspaceNotebookPath);
  await writeWorkspaceFile(
    workspaceNotebookPath,
    source.replace("# preserve_session = false", "# preserve_session = true"),
  );
  const server = startRunServer();
  const rendered = presentationFrame(page);
  const waitForRunMode = async () => {
    await expect(rendered.locator("html")).toHaveAttribute("data-marimo-studio-state", "ready");
    await expect(rendered.getByRole("button", { name: /Widget count:/ })).toBeVisible();
  };

  try {
    await waitForNotebookServer(
      server,
      `${runServerUrl}/dashboard/?access_token=${runServerToken}`,
    );
    await page.goto(`${runServerUrl}/dashboard/?access_token=${runServerToken}`);
    await waitForRunMode();
    await expect(page).toHaveURL(`${runServerUrl}/dashboard/`);
    const scale = labeledSlider(rendered.locator('marimo-cell[name="controls"]'), /^Scale/);
    await scale.press("End");
    await expect(rendered.locator('[mo-value="metric"]')).toHaveText("63");
    const widget = rendered.getByRole("button", { name: "Widget count: 7" });
    await widget.click();
    await expect(rendered.getByRole("button", { name: "Widget count: 8" })).toBeVisible();
    await waitForRunMode();
    const sessionId = await rendered
      .locator("html")
      .evaluate(() => globalThis.__MARIMO_STUDIO_SESSION_ID__);
    expect(sessionId).toMatch(/^s_[\da-z]{6}$/);

    await page.reload();
    await waitForRunMode();

    await expect(page).toHaveURL(`${runServerUrl}/dashboard/`);
    expect(
      await rendered.locator("html").evaluate(() => globalThis.__MARIMO_STUDIO_SESSION_ID__),
    ).toBe(sessionId);
    await expect(rendered.locator('[mo-value="metric"]')).toHaveText("63");
    await expect(rendered.getByRole("button", { name: "Widget count: 8" })).toBeVisible();

    const eligibleDocument = await page.evaluate(() => performance.timeOrigin);
    const eligibleRenderedDocument = await rendered
      .locator("html")
      .evaluate(() => performance.timeOrigin);
    await page.goto("about:blank");
    await page.goBack();
    await waitForRunMode();

    await expect(page).toHaveURL(`${runServerUrl}/dashboard/`);
    expect(
      await rendered.locator("html").evaluate(() => globalThis.__MARIMO_STUDIO_SESSION_ID__),
    ).toBe(sessionId);
    await expect(rendered.locator('[mo-value="metric"]')).toHaveText("63");
    await expect(rendered.getByRole("button", { name: "Widget count: 8" })).toBeVisible();
    if ((await page.evaluate(() => performance.timeOrigin)) === eligibleDocument) {
      expect(await rendered.locator("html").evaluate(() => performance.timeOrigin)).toBe(
        eligibleRenderedDocument,
      );
    }

    const previousDocument = await page.evaluate(() => performance.timeOrigin);
    await page.evaluate(() => globalThis.addEventListener("unload", () => undefined));
    await page.goto("about:blank");
    await page.goBack();
    await waitForRunMode();

    expect(await page.evaluate(() => performance.timeOrigin)).not.toBe(previousDocument);
    await expect(page).toHaveURL(`${runServerUrl}/dashboard/`);
    expect(
      await rendered.locator("html").evaluate(() => globalThis.__MARIMO_STUDIO_SESSION_ID__),
    ).toBe(sessionId);
    await expect(rendered.locator('[mo-value="metric"]')).toHaveText("63");
    await expect(rendered.getByRole("button", { name: "Widget count: 8" })).toBeVisible();
    expect(invalidReplayDocuments).toEqual([]);
  } finally {
    page.off("request", recordReplayDocument);
    try {
      await page.close();
    } finally {
      await stopNotebookServer(server);
    }
  }
});

test("trusted wrapper retains its server-selected runtime", async ({ page }) => {
  const source = await readWorkspaceFile(workspaceNotebookPath);
  await writeWorkspaceFile(
    workspaceNotebookPath,
    source.replace("# preserve_session = false", "# preserve_session = true"),
  );
  const server = startRunServer();
  const rendered = presentationFrame(page);
  const waitForRunMode = async () => {
    await expect(rendered.locator("html")).toHaveAttribute("data-marimo-studio-state", "ready");
  };

  try {
    await waitForNotebookServer(
      server,
      `${runServerUrl}/dashboard/?access_token=${runServerToken}&runtime=server`,
    );
    await page.goto(`${runServerUrl}/dashboard/?access_token=${runServerToken}&runtime=server`);
    await waitForRunMode();
    const sessionId = await rendered
      .locator("html")
      .evaluate(() => globalThis.__MARIMO_STUDIO_SESSION_ID__);

    await rendered.locator("html").evaluate(() => {
      globalThis.parent.postMessage(
        {
          type: "marimo-studio:query-change",
          runtime: "server",
          lifecycleId: 1,
          query: "?runtime=wasm",
        },
        "*",
      );
    });

    await expect(page).toHaveURL(`${runServerUrl}/dashboard/?runtime=server`);
    await page.reload();
    await waitForRunMode();
    await expect(page).toHaveURL(`${runServerUrl}/dashboard/?runtime=server`);
    expect(
      await rendered.locator("html").evaluate(() => ({
        runtime: globalThis.__MARIMO_MOUNT_CONFIG__.runtime,
        sessionId: globalThis.__MARIMO_STUDIO_SESSION_ID__,
      })),
    ).toEqual({ runtime: "server", sessionId });
  } finally {
    try {
      await page.close();
    } finally {
      await stopNotebookServer(server);
    }
  }
});

test("closing wrapper does not attach a delayed replay document", async ({ page }) => {
  const source = await readWorkspaceFile(workspaceNotebookPath);
  await writeWorkspaceFile(
    workspaceNotebookPath,
    source.replace("# preserve_session = false", "# preserve_session = true"),
  );
  const server = startRunServer();
  const rendered = presentationFrame(page);
  let markHeadStarted = () => {};
  const headStarted = new Promise<void>((resolve) => {
    markHeadStarted = resolve;
  });
  let releaseHead = () => {};
  const headRelease = new Promise<void>((resolve) => {
    releaseHead = resolve;
  });
  let markHeadFinished = () => {};
  const headFinished = new Promise<void>((resolve) => {
    markHeadFinished = resolve;
  });
  let intercepted = false;
  const delayReplayHead = async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (
      !intercepted &&
      request.method() === "HEAD" &&
      /^\/_marimo-studio\/presentation\/d\.[^/]+\/dashboard\/$/.test(url.pathname) &&
      url.searchParams.get("marimo_studio_resume") === "1"
    ) {
      intercepted = true;
      markHeadStarted();
      await headRelease;
      try {
        await route.continue();
      } catch {
        // Navigating away owns cancellation of the wrapper's pending preflight.
      } finally {
        markHeadFinished();
      }
      return;
    }
    await route.continue();
  };
  const replayDocuments: string[] = [];
  const recordReplayDocument = (request: Request) => {
    const url = new URL(request.url());
    if (
      request.method() === "GET" &&
      request.resourceType() === "document" &&
      /^\/_marimo-studio\/presentation\/d\.[^/]+\/dashboard\/$/.test(url.pathname) &&
      url.searchParams.get("marimo_studio_resume") === "1"
    ) {
      replayDocuments.push(url.href);
    }
  };

  try {
    await waitForNotebookServer(
      server,
      `${runServerUrl}/dashboard/?access_token=${runServerToken}`,
    );
    await page.goto(`${runServerUrl}/dashboard/?access_token=${runServerToken}`);
    await expect(rendered.locator("html")).toHaveAttribute("data-marimo-studio-state", "ready");
    await page.route("**/*", delayReplayHead);
    page.on("request", recordReplayDocument);

    const reload = page.reload().catch(() => null);
    await headStarted;
    const leave = page.goto("about:blank");
    releaseHead();
    await Promise.all([reload, leave, headFinished]);

    expect(intercepted).toBe(true);
    expect(replayDocuments).toEqual([]);
  } finally {
    releaseHead();
    page.off("request", recordReplayDocument);
    await page.unroute("**/*", delayReplayHead);
    try {
      await page.close();
    } finally {
      await stopNotebookServer(server);
    }
  }
});

test("isolates tabs and rejects poisoned replay storage", async ({ browserDiagnostics, page }) => {
  const tamperedReplay = browserDiagnostics.expectResponse({
    status: 403,
    path: /^\/_marimo-studio\/presentation\/d\.[^/]+\.0{64}\/dashboard\/$/,
  });
  const source = await readWorkspaceFile(workspaceNotebookPath);
  await writeWorkspaceFile(
    workspaceNotebookPath,
    source.replace("# preserve_session = false", "# preserve_session = true"),
  );
  const server = startRunServer();
  const rendered = presentationFrame(page);
  const waitForReady = async (target: ReturnType<typeof presentationFrame>) => {
    await expect(target.locator("html")).toHaveAttribute("data-marimo-studio-state", "ready");
  };
  const sessionId = (target: ReturnType<typeof presentationFrame>) =>
    target.locator("html").evaluate(() => globalThis.__MARIMO_STUDIO_SESSION_ID__);
  const poison = (target: Page, kind: "extra-path" | "private" | "oversized" | "tampered") =>
    target.evaluate((poisonKind) => {
      const key = Object.keys(sessionStorage).find((candidate) =>
        candidate.startsWith("marimo-studio:replay:v1:"),
      );
      if (!key) {
        throw new Error("The wrapper did not retain a replay candidate");
      }
      const stored = sessionStorage.getItem(key);
      if (!stored) {
        throw new Error("The replay candidate is empty");
      }
      if (poisonKind === "oversized") {
        sessionStorage.setItem(key, "x".repeat(32 * 1_024 + 1));
        return;
      }
      const url = new URL(stored);
      if (poisonKind === "private") {
        url.searchParams.set("access_token", "forged");
        url.searchParams.set("marimo_studio_client", "forged-client");
        url.searchParams.set("marimo_studio_lifecycle", "999");
        url.searchParams.set("marimo_studio_server", "forged-server");
        url.searchParams.set("region", "forged");
        url.searchParams.set("runtime", "wasm");
      } else if (poisonKind === "extra-path") {
        url.pathname = `${url.pathname}extra/`;
      } else {
        const segments = url.pathname.split("/");
        const tokenIndex = segments.findIndex((segment) => segment.startsWith("d."));
        if (tokenIndex < 0) {
          throw new Error("The replay candidate has no renewal capability");
        }
        const token = segments[tokenIndex].split(".");
        token[token.length - 1] = "0".repeat(64);
        segments[tokenIndex] = token.join(".");
        url.pathname = segments.join("/");
      }
      sessionStorage.setItem(key, url.toString());
    }, kind);

  let second: Page | undefined;
  let stopReplayHeadTracking = () => {};
  try {
    await waitForNotebookServer(
      server,
      `${runServerUrl}/dashboard/?access_token=${runServerToken}`,
    );
    await page.goto(`${runServerUrl}/dashboard/?access_token=${runServerToken}`);
    await waitForReady(rendered);
    const firstSession = await sessionId(rendered);

    second = await page.context().newPage();
    const secondRendered = presentationFrame(second);
    const pendingReplayHeads = new Set<Request>();
    const replayHead = (request: Request) =>
      request.method() === "HEAD" &&
      /^\/_marimo-studio\/presentation\/d\.[^/]+\/dashboard\/$/.test(
        new URL(request.url()).pathname,
      );
    const startedReplayHead = (request: Request) => {
      if (replayHead(request)) pendingReplayHeads.add(request);
    };
    const finishedReplayHead = (request: Request) => pendingReplayHeads.delete(request);
    second.on("request", startedReplayHead);
    second.on("requestfinished", finishedReplayHead);
    second.on("requestfailed", finishedReplayHead);
    stopReplayHeadTracking = () => {
      second?.off("request", startedReplayHead);
      second?.off("requestfinished", finishedReplayHead);
      second?.off("requestfailed", finishedReplayHead);
    };
    await second.goto(`${runServerUrl}/dashboard/`);
    await waitForReady(secondRendered);
    let currentSession = await sessionId(secondRendered);
    expect(currentSession).not.toBe(firstSession);

    const storedBeforeAuthoredMessages = await second.evaluate(() =>
      Object.entries(sessionStorage).find(([key]) => key.startsWith("marimo-studio:replay:v1:")),
    );
    await secondRendered.locator("html").evaluate(() => {
      globalThis.parent.postMessage(
        {
          type: "marimo-studio:replay-document",
          runtime: "server",
          lifecycleId: 1,
          view: "dashboard",
          url: "x".repeat(32 * 1_024 + 1),
          extra: true,
        },
        "*",
      );
    });
    await expect
      .poll(() =>
        second?.evaluate(() =>
          Object.entries(sessionStorage).find(([key]) =>
            key.startsWith("marimo-studio:replay:v1:"),
          ),
        ),
      )
      .toEqual(storedBeforeAuthoredMessages);

    await poison(second, "private");
    await second.reload();
    await waitForReady(secondRendered);
    expect(await sessionId(secondRendered)).toBe(currentSession);
    await expect(second).toHaveURL(`${runServerUrl}/dashboard/`);
    expect(
      await secondRendered.locator("html").evaluate(() => {
        const query = new URLSearchParams(location.search);
        return {
          accessToken: query.get("access_token"),
          client: query.get("marimo_studio_client"),
          lifecycle: query.get("marimo_studio_lifecycle"),
          region: query.get("region"),
          runtime: query.get("runtime"),
        };
      }),
    ).toEqual({
      accessToken: null,
      client: null,
      lifecycle: null,
      region: null,
      runtime: null,
    });

    await poison(second, "oversized");
    await second.reload();
    await waitForReady(secondRendered);
    expect(await sessionId(secondRendered)).not.toBe(currentSession);
    currentSession = await sessionId(secondRendered);

    await poison(second, "extra-path");
    await second.reload();
    await waitForReady(secondRendered);
    expect(await sessionId(secondRendered)).not.toBe(currentSession);
    currentSession = await sessionId(secondRendered);

    for (const status of [202, 204, 200, 302]) {
      let intercepted = false;
      const rejectProbe = async (route: Route) => {
        const request = route.request();
        if (
          !intercepted &&
          request.method() === "HEAD" &&
          new URL(request.url()).searchParams.get("marimo_studio_resume") === "1"
        ) {
          intercepted = true;
          await route.fulfill({
            status,
            headers: status === 302 ? { location: `${runServerUrl}/dashboard/` } : {},
          });
          return;
        }
        await route.continue();
      };
      await second.route("**/*", rejectProbe);
      try {
        await second.reload();
        await waitForReady(secondRendered);
      } finally {
        await second.unroute("**/*", rejectProbe);
      }
      expect(intercepted).toBe(true);
      expect(await sessionId(secondRendered)).not.toBe(currentSession);
      currentSession = await sessionId(secondRendered);
      await expect(second).toHaveURL(`${runServerUrl}/dashboard/`);
    }

    const rejectedTamperedProbe = browserDiagnostics.expectRequestAbort({
      origin: runServerUrl,
      method: "HEAD",
      path: /^\/_marimo-studio\/presentation\/d\.[^/]+\.0{64}\/dashboard\/$/,
      count: 1,
      required: false,
    });
    await poison(second, "tampered");
    await second.reload();
    await waitForReady(secondRendered);
    expect(await sessionId(secondRendered)).not.toBe(currentSession);
    await expect(secondRendered.locator('[mo-value="metric"]')).toHaveText("42");
    await second.waitForLoadState("networkidle");
    await expect
      .poll(async () => {
        if (pendingReplayHeads.size > 0) return false;
        await new Promise((resolve) => setTimeout(resolve, 250));
        return pendingReplayHeads.size === 0;
      })
      .toBe(true);
    tamperedReplay.recovered();
    await recoverRequestAbort(rejectedTamperedProbe);
  } finally {
    stopReplayHeadTracking();
    await second?.close();
    try {
      await page.close();
    } finally {
      await stopNotebookServer(server);
    }
  }
});
