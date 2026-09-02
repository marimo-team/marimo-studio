import { expect, test } from "@playwright/test";
import { cp, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";

import { fixtureDirectory } from "../scripts/paths.mjs";
import { executeCodeMode, studioEditorSessionId } from "./authoring-test-support.ts";
import { editorFrame } from "./fixture.ts";
import {
  availablePort,
  closeFailedNotebookServer,
  startNotebookServer,
  stopNotebookServer,
  waitForNotebookServer,
} from "./notebook-server.ts";

test("preserves an untitled native session through save and Studio entry", async ({
  browser,
}, testInfo) => {
  test.setTimeout(120_000);
  const root = await mkdtemp(resolve(tmpdir(), "marimo-studio-host-session-"));
  const workspace = resolve(root, "workspace");
  await cp(fixtureDirectory, workspace, { recursive: true });
  const server = startNotebookServer({
    authentication: ["--no-token"],
    command: "edit",
    editRoot: "marimo",
    port: await availablePort(),
    target: workspace,
  });
  const context = await browser.newContext();
  let stopped = false;
  try {
    await waitForNotebookServer(server, `${server.serverUrl}/`);
    const page = await context.newPage();
    const instantiated = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname.endsWith("/api/kernel/instantiate") &&
        response.ok(),
    );
    await page.goto(`${server.serverUrl}/?file=__new__s_host01`);
    const sessionId = (await instantiated).request().headers()["marimo-session-id"];
    expect(sessionId).toMatch(/^s_[a-z0-9]{6}$/);

    const cell = page.locator("[data-cell-id]").first();
    await cell.getByRole("textbox").fill("saved = True\nsaved");
    await cell.hover();
    await cell.locator('button[data-testid="run-button"]:not(:disabled)').click();
    await expect(cell.locator("..")).toHaveAttribute("data-status", "idle");
    await page.getByTestId("save-button").click();
    await page.getByPlaceholder("filename").fill("host-save.py");
    await page.getByText("Save as: host-save.py", { exact: true }).click();

    await expect(page).toHaveURL(`${server.serverUrl}/?file=host-save.py`);
    await expect(page.locator("#marimo-studio-host")).toHaveCount(0);
    await expect(page.locator(".cm-content").first()).toContainText("saved = True");

    await page.goto(`${server.serverUrl}/studio/?file=host-save.py`);
    await expect(page.getByRole("heading", { name: "Create the first view" })).toBeVisible();
    await page.getByRole("button", { name: "Create dashboard" }).click();
    await expect(page).toHaveURL(`${server.serverUrl}/studio/dashboard/?file=host-save.py`);
    expect(await studioEditorSessionId(page)).toBe(sessionId);
    await executeCodeMode(
      editorFrame(page),
      "host-save.py",
      sessionId,
      `
import marimo_studio.agent as studio_agent

view = studio_agent.current_workspace().view("dashboard")
shown = await view.show()
shown.to_dict()
`,
    );

    const direct = await context.newPage();
    await direct.goto(`${server.serverUrl}/studio/dashboard/?file=notebook.py`);
    await expect(editorFrame(direct).locator("[data-cell-id]").first()).toBeVisible();
    const directSessionId = await studioEditorSessionId(direct);
    await direct.goto(`${server.serverUrl}/?file=notebook.py`);
    await expect(direct.locator("[data-cell-id]").first()).toBeVisible();
    await direct.goto(`${server.serverUrl}/studio/dashboard/?file=notebook.py`);
    expect(await studioEditorSessionId(direct)).toBe(directSessionId);
    await expect(editorFrame(direct).locator("[data-cell-id]").first()).toBeVisible();
    await direct.close();

    await stopNotebookServer(server);
    stopped = true;
  } finally {
    await context.close();
    const cleanupFailure = !stopped ? await closeFailedNotebookServer(server) : undefined;
    if (cleanupFailure !== undefined) {
      await testInfo.attach("notebook-server-cleanup", {
        body: Buffer.from(cleanupFailure.message),
        contentType: "text/plain",
      });
    }
    await rm(root, { force: true, recursive: true });
  }
});
