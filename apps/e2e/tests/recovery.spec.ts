import { expect as playwrightExpect, test as playwrightTest, type Page } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";

import { configDirectory, repositoryDirectory } from "../scripts/paths.mjs";
import {
  editorFrame,
  expect,
  studioEntryUrl,
  previewFrame,
  readWorkspaceFile,
  restoreWorkspace,
  test,
  waitForPreview,
  workspaceNotebookPath,
  writeWorkspaceFile,
} from "./fixture.ts";

const runShortcut = process.platform === "darwin" ? "Meta+Enter" : "Control+Enter";
const selectAllShortcut = process.platform === "darwin" ? "Meta+a" : "Control+a";
const originalMetricSource = "metric = scale.value * 21\nmetric";
const runServerUrl = "http://127.0.0.1:4323";
const runServerToken = "recovery-e2e-token";
const editServerUrl = "http://127.0.0.1:4324";

declare global {
  var __studioEventSourceCount: number | undefined;
  var __studioEventSources: EventSource[] | undefined;
  var __studioWebSocketObservations: WebSocketObservation[] | undefined;
}

interface WebSocketObservation {
  documentUrl: string;
  socketUrl: string;
  closeCode?: number;
  closeReason?: string;
}

const startNotebookServer = (
  command: "edit" | "run",
  port: number,
  authentication: readonly string[],
) => {
  const child = spawn(
    "uv",
    [
      "run",
      "--frozen",
      "--group",
      "e2e",
      "marimo",
      command,
      workspaceNotebookPath,
      "--no-sandbox",
      "--headless",
      ...authentication,
      "--host",
      "127.0.0.1",
      "--port",
      String(port),
    ],
    {
      cwd: repositoryDirectory,
      detached: process.platform !== "win32",
      env: {
        ...process.env,
        PYTHONUNBUFFERED: "1",
        XDG_CONFIG_HOME: configDirectory,
      },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  let output = "";
  child.stdout?.on("data", (data: Buffer) => {
    output += data.toString();
  });
  child.stderr?.on("data", (data: Buffer) => {
    output += data.toString();
  });
  return { output: () => output, process: child };
};

const startRunServer = () => startNotebookServer("run", 4323, ["--token-password", runServerToken]);

const startEditServer = () => startNotebookServer("edit", 4324, ["--no-token"]);

const waitForServer = async (
  server: ReturnType<typeof startNotebookServer>,
  url: string,
): Promise<void> => {
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    if (server.process.exitCode !== null) {
      throw new Error(`Notebook server exited during startup\n${server.output()}`);
    }
    try {
      const response = await fetch(url);
      await response.body?.cancel();
      if (response.ok) {
        return;
      }
    } catch {
      // The socket is unavailable until Marimo starts listening.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Notebook server did not start\n${server.output()}`);
};

const stopServer = async (child: ChildProcess): Promise<void> => {
  const stopped = () => child.exitCode !== null || child.signalCode !== null;
  const pid = child.pid;
  if (stopped() || pid === undefined) {
    return;
  }
  const kill = (signal: NodeJS.Signals) => {
    try {
      if (process.platform === "win32") {
        child.kill(signal);
      } else {
        process.kill(-pid, signal);
      }
    } catch (error) {
      if (!(error instanceof Error && "code" in error && error.code === "ESRCH")) {
        throw error;
      }
    }
  };
  const exited = new Promise<void>((resolve) => child.once("exit", () => resolve()));
  kill("SIGTERM");
  let timeout: ReturnType<typeof setTimeout> | undefined;
  await Promise.race([
    exited,
    new Promise((resolve) => {
      timeout = setTimeout(resolve, 5_000);
    }),
  ]);
  clearTimeout(timeout);
  if (stopped()) {
    return;
  }
  kill("SIGKILL");
  await exited;
};

const replaceMetricCell = async (page: Page, source: string) => {
  const cell = editorFrame(page)
    .locator(".cm-content")
    .filter({ hasText: /(?:metric|replacement) = scale\.value \* 21/ })
    .first();
  await cell.click();
  await cell.press(selectAllShortcut);
  await page.keyboard.insertText(source);
  await page.keyboard.press(runShortcut);
};

const waitForMetricSource = () =>
  expect
    .poll(async () => {
      const source = await readWorkspaceFile(workspaceNotebookPath);
      return source.includes("metric = scale.value * 21") && !source.includes("replacement =");
    })
    .toBe(true);

const eventSourceCount = async (page: Page): Promise<number> =>
  (
    await Promise.all(
      page
        .frames()
        .map((frame) =>
          frame.evaluate(() => globalThis.__studioEventSourceCount ?? 0).catch(() => 0),
        ),
    )
  ).reduce((total, count) => total + count, 0);

const webSocketObservations = async (page: Page): Promise<WebSocketObservation[]> =>
  (
    await Promise.all(
      page
        .frames()
        .map((frame) =>
          frame
            .evaluate(() => globalThis.__studioWebSocketObservations ?? [])
            .catch((): WebSocketObservation[] => []),
        ),
    )
  ).flat();

const isEditorSocket = (observation: WebSocketObservation): boolean =>
  new URL(observation.documentUrl).pathname.includes("/_marimo-studio/editor/");

playwrightTest(
  "a fresh Studio tab starts after the server restarts with a stale tab open",
  async ({ context, page }) => {
    await restoreWorkspace();
    await context.addInitScript(() => {
      const NativeEventSource = globalThis.EventSource;
      const NativeWebSocket = globalThis.WebSocket;
      globalThis.__studioEventSourceCount = 0;
      globalThis.__studioEventSources = [];
      globalThis.__studioWebSocketObservations = [];
      globalThis.EventSource = class extends NativeEventSource {
        constructor(url: string | URL, eventSourceInitDict?: EventSourceInit) {
          super(url, eventSourceInitDict);
          globalThis.__studioEventSourceCount = (globalThis.__studioEventSourceCount ?? 0) + 1;
          globalThis.__studioEventSources?.push(this);
        }
      };
      globalThis.WebSocket = class extends NativeWebSocket {
        constructor(url: string | URL, protocols: string | string[] = []) {
          super(url, protocols);
          const observation: WebSocketObservation = {
            documentUrl: globalThis.location.href,
            socketUrl: this.url,
          };
          globalThis.__studioWebSocketObservations?.push(observation);
          this.addEventListener("close", (event) => {
            observation.closeCode = event.code;
            observation.closeReason = event.reason;
          });
        }
      };
    });
    let server = startEditServer();
    let fresh: Page | undefined;

    try {
      await waitForServer(server, editServerUrl);
      await page.goto(editServerUrl);
      await waitForPreview(page);
      await playwrightExpect.poll(() => eventSourceCount(page)).toBe(1);
      await playwrightExpect
        .poll(async () => (await webSocketObservations(page)).some(isEditorSocket))
        .toBe(true);
      await playwrightExpect
        .poll(() =>
          page.evaluate(
            () => globalThis.__studioEventSources?.[0]?.readyState === EventSource.OPEN,
          ),
        )
        .toBe(true);

      await stopServer(server.process);
      server = startEditServer();
      await waitForServer(server, editServerUrl);
      await playwrightExpect
        .poll(() =>
          page.evaluate(
            () => globalThis.__studioEventSources?.[0]?.readyState === EventSource.CLOSED,
          ),
        )
        .toBe(true);
      await playwrightExpect
        .poll(async () =>
          (await webSocketObservations(page)).some(
            (observation) =>
              isEditorSocket(observation) &&
              observation.closeCode === 1000 &&
              observation.closeReason === "MARIMO_NO_SESSION",
          ),
        )
        .toBe(true);

      const current = await context.newPage();
      fresh = current;
      await current.goto(editServerUrl);
      const preview = await waitForPreview(current);
      await playwrightExpect(preview.getByText("Projected total:")).toBeVisible();
      await playwrightExpect.poll(() => eventSourceCount(current)).toBe(1);
      playwrightExpect(server.output()).not.toContain("Exception in ASGI application");
    } finally {
      await fresh?.close();
      await stopServer(server.process);
      await restoreWorkspace();
    }
  },
);

test("restores a value host after its notebook value returns", async ({ page }) => {
  await page.goto(studioEntryUrl);
  const preview = await waitForPreview(page);
  const value = preview.locator('[mo-value="metric"]');
  const initial = await value.textContent();
  expect(initial).toMatch(/^\d+$/);
  let restored = false;

  try {
    await replaceMetricCell(page, "replacement = scale.value * 21\nreplacement");

    await expect(value).toHaveAttribute("data-state", "error");
    await expect(preview.locator('marimo-cell[name="controls"]')).toHaveAttribute(
      "data-state",
      "ready",
    );
    expect(
      await preview.locator("html").evaluate(() => globalThis.marimoStudio.diagnostics()),
    ).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          code: expect.stringMatching(/^(missing-variable|value-variable-not-found)$/),
          severity: "error",
          target: "metric",
        }),
      ]),
    );

    await replaceMetricCell(page, originalMetricSource);
    await expect(value).toHaveAttribute("data-state", "ready");
    await waitForMetricSource();
    restored = true;
    await expect(value).toHaveText(initial ?? "");
    await expect(previewFrame(page).locator("html")).toHaveAttribute(
      "data-marimo-studio-state",
      "ready",
    );
  } finally {
    if (!restored) {
      await replaceMetricCell(page, originalMetricSource);
      await expect(value).toHaveAttribute("data-state", "ready");
      await waitForMetricSource();
    }
  }
});

test("preserves run-mode kernel state across a page reload", async ({ page }) => {
  const source = await readWorkspaceFile(workspaceNotebookPath);
  await writeWorkspaceFile(
    workspaceNotebookPath,
    source.replace("# preserve_session = false", "# preserve_session = true"),
  );
  const server = startRunServer();
  const waitForRunMode = async () => {
    await expect(page.locator("html")).toHaveAttribute("data-marimo-studio-state", "ready");
    await expect(page.getByRole("button", { name: /Widget count:/ })).toBeVisible();
  };

  try {
    await waitForServer(server, `${runServerUrl}/dashboard/?access_token=${runServerToken}`);
    await page.goto(`${runServerUrl}/dashboard/?access_token=${runServerToken}`);
    await waitForRunMode();
    const scale = page.locator('marimo-cell[name="controls"]').getByRole("slider");
    await scale.press("End");
    await expect(page.locator('[mo-value="metric"]')).toHaveText("63");
    const widget = page.getByRole("button", { name: "Widget count: 7" });
    await widget.click();
    await expect(page.getByRole("button", { name: "Widget count: 8" })).toBeVisible();
    const sessionId = await page.evaluate(() => globalThis.__MARIMO_STUDIO_SESSION_ID__);
    expect(sessionId).toMatch(/^s_[\da-z]{6}$/);

    await page.reload();
    await waitForRunMode();

    expect(await page.evaluate(() => globalThis.__MARIMO_STUDIO_SESSION_ID__)).toBe(sessionId);
    await expect(page.locator('[mo-value="metric"]')).toHaveText("63");
    await expect(page.getByRole("button", { name: "Widget count: 8" })).toBeVisible();
  } finally {
    try {
      await page.close();
    } finally {
      await stopServer(server.process);
    }
  }
});
