import type { Page } from "@playwright/test";

import { spawn, type ChildProcess } from "node:child_process";

import { configDirectory, repositoryDirectory } from "../scripts/paths.mjs";
import {
  editorFrame,
  expect,
  studioEntryUrl,
  previewFrame,
  readWorkspaceFile,
  test,
  waitForPreview,
  workspaceNotebookPath,
  writeWorkspaceFile,
} from "./fixture.ts";

const runShortcut = process.platform === "darwin" ? "Meta+Enter" : "Control+Enter";
const selectAllShortcut = process.platform === "darwin" ? "Meta+a" : "Control+a";
const originalMetricSource = "metric = scale.value * 21\nmetric";
const runServerUrl = "http://127.0.0.1:4323";

const startRunServer = (): { output: () => string; process: ChildProcess } => {
  const child = spawn(
    "uv",
    [
      "run",
      "--frozen",
      "--group",
      "e2e",
      "marimo",
      "run",
      workspaceNotebookPath,
      "--no-sandbox",
      "--headless",
      "--no-token",
      "--host",
      "127.0.0.1",
      "--port",
      "4323",
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

const waitForRunServer = async (server: ReturnType<typeof startRunServer>): Promise<void> => {
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    if (server.process.exitCode !== null) {
      throw new Error(`Run server exited during startup\n${server.output()}`);
    }
    try {
      const response = await fetch(`${runServerUrl}/dashboard/`);
      await response.body?.cancel();
      if (response.ok) {
        return;
      }
    } catch {
      // The socket is unavailable until Marimo starts listening.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Run server did not start\n${server.output()}`);
};

const stopRunServer = async (child: ChildProcess): Promise<void> => {
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
    await waitForRunServer(server);
    await page.goto(`${runServerUrl}/dashboard/`);
    await waitForRunMode();
    const scale = page.locator('marimo-cell[name="controls"]').getByRole("slider");
    await scale.press("End");
    await expect(page.locator('[mo-value="metric"]')).toHaveText("63");
    const widget = page.getByRole("button", { name: "Widget count: 7" });
    await widget.click();
    await expect(page.getByRole("button", { name: "Widget count: 8" })).toBeVisible();
    const sessionId = await page.evaluate(
      () =>
        (globalThis as typeof globalThis & { __MARIMO_STUDIO_SESSION_ID__?: string })
          .__MARIMO_STUDIO_SESSION_ID__,
    );
    expect(sessionId).toMatch(/^s_[\da-z]{6}$/);

    await page.reload();
    await waitForRunMode();

    expect(
      await page.evaluate(
        () =>
          (globalThis as typeof globalThis & { __MARIMO_STUDIO_SESSION_ID__?: string })
            .__MARIMO_STUDIO_SESSION_ID__,
      ),
    ).toBe(sessionId);
    await expect(page.locator('[mo-value="metric"]')).toHaveText("63");
    await expect(page.getByRole("button", { name: "Widget count: 8" })).toBeVisible();
  } finally {
    await stopRunServer(server.process);
  }
});
