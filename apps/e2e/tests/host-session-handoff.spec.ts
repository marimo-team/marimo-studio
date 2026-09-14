import { expect, test } from "@playwright/test";
import { cp, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";

import { e2eNetwork } from "../scripts/network.mjs";
import { fixtureDirectory } from "../scripts/paths.mjs";
import { executeCodeMode, studioEditorSessionId } from "./authoring-test-support.ts";
import { observeBrowserContext } from "./browser-diagnostics.ts";
import { editorFrame, recoverWorkspaceEventStream, waitForPreview } from "./fixture.ts";
import {
  closeFailedNotebookServer,
  startNotebookServer,
  stopNotebookServer,
  waitForNotebookServer,
} from "./notebook-server.ts";

test("preserves the native kernel through first save and Studio entry", async ({
  browser,
}, testInfo) => {
  const root = await mkdtemp(resolve(tmpdir(), "marimo-studio-host-session-"));
  const workspace = resolve(root, "workspace");
  await cp(fixtureDirectory, workspace, { recursive: true });
  const server = startNotebookServer({
    authentication: ["--no-token"],
    command: "edit",
    editRoot: "marimo",
    port: e2eNetwork.main.hostSession.port,
    target: workspace,
  });
  const context = await browser.newContext();
  const diagnostics = observeBrowserContext(context);
  const filenameFallback = diagnostics.expectConsole({
    type: "warning",
    text: /^No filename provided, using fallback$/,
    required: false,
  });
  const dialogDescription = diagnostics.expectConsole({
    type: "warning",
    text: /Missing `Description` or `aria-describedby=\{undefined\}` for \{DialogContent\}/,
    required: false,
  });
  const closedLspHealth = diagnostics.expectConsole({
    type: "error",
    text: /^Error requesting .*\/api\/lsp\/health TypeError: Failed to fetch$/,
    required: false,
  });
  const closedUsageStats = diagnostics.expectConsole({
    type: "error",
    text: /^Failed to handle request: getUsageStats TypeError: Failed to fetch$/,
    required: false,
  });
  const workspaceStream = diagnostics.expectWorkspaceEventStreamReplacement(
    `${server.serverUrl}/_marimo-studio/dev/events`,
  );
  let diagnosticsClosed = false;
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
    const resumedNativeSession = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return (
        response.request().method() === "GET" &&
        url.pathname === "/" &&
        url.searchParams.get("file") === "host-save.py" &&
        url.searchParams.get("session_id") === sessionId &&
        response.ok()
      );
    });

    const cell = page.locator("[data-cell-id]").first();
    await cell.getByRole("textbox").fill("saved = []\nsaved");
    await cell.hover();
    await cell.locator('button[data-testid="run-button"]:not(:disabled)').click();
    await expect(cell.locator("..")).toHaveAttribute("data-status", "idle");
    await page.getByTestId("save-button").click();
    await page.getByPlaceholder("filename").click();
    await page.getByPlaceholder("filename").fill("host-save.py");
    await page.getByText("Save as: host-save.py", { exact: true }).click();

    await resumedNativeSession;
    await expect(page).toHaveURL(`${server.serverUrl}/?file=host-save.py`);
    await expect(page.locator("#marimo-studio-host")).toHaveCount(0);
    await expect(page.locator(".cm-content").first()).toContainText("saved = []");
    await executeCodeMode(page, "host-save.py", sessionId, 'saved.append("kept")');

    await page.goto(`${server.serverUrl}/studio/?file=host-save.py`);
    await expect(page.getByText("Add view", { exact: true })).toBeVisible();
    await page.getByText("Add view", { exact: true }).click();
    await page.getByRole("button", { name: "Create view" }).click();
    await expect(page).toHaveURL(`${server.serverUrl}/studio/dashboard/?file=host-save.py`);
    await expect(editorFrame(page).locator("[data-cell-id]").first()).toBeVisible();
    const connectedSession = await studioEditorSessionId(page);
    const takeover = editorFrame(page).getByRole("button", { name: "Take over", exact: true });
    if (await takeover.isVisible()) {
      await takeover.click();
      await expect(takeover).toHaveCount(0);
    }
    await recoverWorkspaceEventStream(workspaceStream);
    await waitForPreview(page);
    await executeCodeMode(
      editorFrame(page),
      "host-save.py",
      connectedSession,
      `
assert saved == ["kept"]
import marimo_studio.agent as studio_agent

shown = await studio_agent.current_workspace().view("dashboard").show()
shown.to_dict()
      `,
    );
    await waitForPreview(page);

    filenameFallback.recovered();
    dialogDescription.recovered();
    closedLspHealth.recovered();
    closedUsageStats.recovered();
    await diagnostics.close();
    diagnosticsClosed = true;
    expect(diagnostics.messages, "unexpected browser diagnostics").toEqual([]);
    await stopNotebookServer(server);
    stopped = true;
  } finally {
    if (!diagnosticsClosed) {
      await diagnostics.close();
      if (diagnostics.messages.length > 0) {
        await testInfo.attach("browser-diagnostics", {
          body: Buffer.from(diagnostics.messages.join("\n")),
          contentType: "text/plain",
        });
      }
    }
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
