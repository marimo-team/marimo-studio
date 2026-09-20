import type { Page, Route } from "@playwright/test";

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
import { runServerToken, runServerUrl, startRunServer } from "./recovery-support.ts";

test.use({ services: [] });

test("preserves run-mode kernel state across a page reload", async ({ page }) => {
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
    await server.waitUntilReady(`${runServerUrl()}/dashboard/?access_token=${runServerToken}`);
    await page.goto(`${runServerUrl()}/dashboard/?access_token=${runServerToken}`);
    await waitForRunMode();
    await expect(page).toHaveURL(`${runServerUrl()}/dashboard/`);
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

    await expect(page).toHaveURL(`${runServerUrl()}/dashboard/`);
    expect(
      await rendered.locator("html").evaluate(() => globalThis.__MARIMO_STUDIO_SESSION_ID__),
    ).toBe(sessionId);
    await expect(rendered.locator('[mo-value="metric"]')).toHaveText("63");
    await expect(rendered.getByRole("button", { name: "Widget count: 8" })).toBeVisible();
  } finally {
    try {
      await page.close();
    } finally {
      await server.close();
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
    await server.waitUntilReady(
      `${runServerUrl()}/dashboard/?access_token=${runServerToken}&runtime=server`,
    );
    await page.goto(`${runServerUrl()}/dashboard/?access_token=${runServerToken}&runtime=server`);
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

    await expect(page).toHaveURL(`${runServerUrl()}/dashboard/?runtime=server`);
    await page.reload();
    await waitForRunMode();
    await expect(page).toHaveURL(`${runServerUrl()}/dashboard/?runtime=server`);
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
      await server.close();
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
  try {
    await server.waitUntilReady(`${runServerUrl()}/dashboard/?access_token=${runServerToken}`);
    await page.goto(`${runServerUrl()}/dashboard/?access_token=${runServerToken}`);
    await expect(rendered.locator("html")).toHaveAttribute("data-marimo-studio-state", "ready");
    await page.route("**/*", delayReplayHead);

    const reload = page.reload().catch(() => null);
    await headStarted;
    const leave = page.goto("about:blank");
    releaseHead();
    await Promise.all([reload, leave, headFinished]);

    expect(intercepted).toBe(true);
    await expect(page).toHaveURL("about:blank");
  } finally {
    releaseHead();
    await page.unroute("**/*", delayReplayHead);
    try {
      await page.close();
    } finally {
      await server.close();
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
  try {
    await server.waitUntilReady(`${runServerUrl()}/dashboard/?access_token=${runServerToken}`);
    await page.goto(`${runServerUrl()}/dashboard/?access_token=${runServerToken}`);
    await waitForReady(rendered);
    const firstSession = await sessionId(rendered);

    second = await page.context().newPage();
    const secondRendered = presentationFrame(second);
    await second.goto(`${runServerUrl()}/dashboard/`);
    await waitForReady(secondRendered);
    let currentSession = await sessionId(secondRendered);
    expect(currentSession).not.toBe(firstSession);

    const replayStorage = () =>
      second?.evaluate(() =>
        Object.entries(sessionStorage).find(([key]) => key.startsWith("marimo-studio:replay:v1:")),
      );
    const retainedReplay = await replayStorage();
    if (!retainedReplay) {
      throw new Error("The wrapper did not retain its current replay candidate");
    }
    for (const malformed of [
      { url: "x".repeat(32 * 1_024 + 1) },
      { url: retainedReplay[1], extra: true },
    ]) {
      await secondRendered.locator("html").evaluate((_root, candidate) => {
        globalThis.parent.postMessage(
          {
            type: "marimo-studio:replay-document",
            runtime: "server",
            lifecycleId: 1,
            view: "dashboard",
            ...candidate,
          },
          "*",
        );
      }, malformed);
      await expect.poll(replayStorage).toEqual(retainedReplay);
      expect(await sessionId(secondRendered)).toBe(currentSession);
    }

    await poison(second, "private");
    await second.reload();
    await waitForReady(secondRendered);
    expect(await sessionId(secondRendered)).toBe(currentSession);
    await expect(second).toHaveURL(`${runServerUrl()}/dashboard/`);
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

    for (const status of [204, 200, 302]) {
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
            headers: status === 302 ? { location: `${runServerUrl()}/dashboard/` } : {},
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
      await expect(second).toHaveURL(`${runServerUrl()}/dashboard/`);
    }

    const rejectedTamperedProbe = browserDiagnostics.expectRequestAbort({
      origin: runServerUrl(),
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
    tamperedReplay.recovered();
    await recoverRequestAbort(rejectedTamperedProbe);
  } finally {
    await second?.close();
    try {
      await page.close();
    } finally {
      await server.close();
    }
  }
});
