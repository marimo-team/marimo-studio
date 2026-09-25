import { mountConfigSchema } from "@marimo-studio/protocol/runtime-config";
import { expect } from "@playwright/test";
import { cp, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";

import { e2eNetwork } from "../scripts/network.ts";
import { fixtureDirectory } from "../scripts/paths.ts";
import {
  executeCodeMode,
  expectFirstSaveRetirement,
  studioEditorSessionId,
} from "./authoring-test-support.ts";
import { observeBrowserContext } from "./browser-diagnostics.ts";
import {
  captureProjectionRefresh,
  recoverProjectionRefresh,
  editorFrame,
  previewFrame,
  recoverRequestAbort,
  recoverWorkspaceEventStream,
  waitForPreview,
} from "./fixture.ts";
import { test } from "./network-fixture.ts";
import { closeFailedNotebookServer, startNotebookServer } from "./notebook-server.ts";

test.describe.configure({ mode: "serial" });

for (const editRoot of ["marimo", "studio"] as const) {
  test(`preserves notebook ownership through launcher, first save, and restart (${editRoot})`, async ({
    browser,
  }, testInfo) => {
    const root = await mkdtemp(resolve(tmpdir(), "marimo-studio-host-session-"));
    const workspace = resolve(root, "workspace");
    await cp(fixtureDirectory, workspace, { recursive: true });
    const server = startNotebookServer({
      authentication: ["--no-token"],
      command: "edit",
      editRoot,
      endpoint: e2eNetwork.main.hostSession,
      target: workspace,
    });
    const context = await browser.newContext();
    const diagnostics = observeBrowserContext(context);
    const filenameFallback = diagnostics.expectConsole({
      type: "warning",
      text: /^No filename provided, using fallback$/,
      count: 3,
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
    const closedSandboxStatus = diagnostics.expectConsole({
      type: "error",
      text: /^Failed to handle request: getSandbox TypeError: Failed to fetch(?:\n|$)/,
      required: false,
    });
    const closedSandboxRequest = diagnostics.expectRequestFailure({
      origin: server.serverUrl,
      method: "POST",
      path: /^(?:\/_marimo-studio\/editor)?\/api\/packages\/sandbox$/,
      errorText: "net::ERR_ABORTED",
      required: false,
    });
    const workspaceStream = diagnostics.expectWorkspaceEventStreamReplacement(
      `${server.serverUrl}/_marimo-studio/dev/events`,
    );
    let diagnosticsClosed = false;
    let stopped = false;
    try {
      await server.waitUntilReady(`${server.serverUrl}/`);
      const launcher = await context.newPage();
      await launcher.goto(`${server.serverUrl}/`);
      const instantiated = context.waitForEvent("response", {
        predicate: (response) =>
          response.request().method() === "POST" &&
          new URL(response.url()).pathname.endsWith("/api/kernel/instantiate") &&
          response.ok(),
      });
      const opened = context.waitForEvent("page");
      await launcher.getByRole("link", { name: "Create a new notebook" }).click();
      const page = await opened;
      const sessionId = (await instantiated).request().headers()["marimo-session-id"];
      expect(sessionId).toMatch(/^s_[a-z0-9]{6}$/);

      const cell = page.locator("[data-cell-id]").first();
      await cell.getByRole("textbox").fill("saved = []\na = 42\na");
      await cell.hover();
      await cell.locator('button[data-testid="run-button"]:not(:disabled)').click();
      await expect(cell.locator("..")).toHaveAttribute("data-status", "idle");
      const retiredSave = expectFirstSaveRetirement(diagnostics, server.serverUrl);
      if (editRoot === "studio") {
        await page.locator("#filename-input input").fill("host-save.py");
        await page.locator("#filename-input input").press("Enter");
        await expect(page).toHaveURL(`${server.serverUrl}/studio/dashboard/?file=host-save.py`);
        await expect(editorFrame(page).locator(".cm-content").first()).toContainText("saved = []");
        await expect(editorFrame(page).getByText("Reconnected", { exact: true })).toHaveCount(0);
        await executeCodeMode(editorFrame(page), "host-save.py", sessionId, 'saved.append("kept")');
      } else {
        const resumedNativeSession = page.waitForResponse((response) => {
          const url = new URL(response.url());
          return (
            response.request().method() === "GET" &&
            url.pathname === "/" &&
            url.searchParams.get("file") === "host-save.py" &&
            url.searchParams.get("session_id") === sessionId &&
            !url.searchParams.has("marimo_studio_handoff") &&
            response.ok()
          );
        });
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
      }
      retiredSave.recovered();
      await expect(page.getByText("Add view", { exact: true })).toBeVisible();
      await page.getByText("Add view", { exact: true }).click();
      await page.getByRole("radio", { name: /^HTML document/ }).check();
      await page.getByRole("button", { name: "Create view" }).click();
      await expect(page).toHaveURL(`${server.serverUrl}/studio/dashboard/?file=host-save.py`);
      await expect(editorFrame(page).locator("[data-cell-id]").first()).toBeVisible();
      const connectedSession = await studioEditorSessionId(page);
      const takeover = editorFrame(page).getByRole("button", { name: "Take over", exact: true });
      if (editRoot === "studio") {
        expect(connectedSession).toBe(sessionId);
        await expect(takeover).toHaveCount(0);
      } else if (await takeover.isVisible()) {
        await takeover.click();
        await expect(takeover).toHaveCount(0);
      }
      await recoverWorkspaceEventStream(workspaceStream);
      await waitForPreview(page);
      // Replacing a preview document can cancel the retiring document's model
      // notification. The replacement establishes fresh model state on its own
      // route, so each expectation names only the document being replaced.
      const expectRetiringModelNotification = async () => {
        const mount = mountConfigSchema.parse(
          await previewFrame(page)
            .locator("html")
            .evaluate(() => {
              if (!("__MARIMO_MOUNT_CONFIG__" in globalThis)) {
                throw new Error("The preview mount configuration is unavailable.");
              }
              return globalThis.__MARIMO_MOUNT_CONFIG__;
            }),
        );
        const support = new URL(mount.supportUrl, server.serverUrl);
        const boundary = support.pathname.indexOf("/_marimo-studio/views/");
        if (boundary < 0) throw new Error("The preview has no scoped support URL.");
        return diagnostics.expectRequestAbort({
          origin: server.serverUrl,
          method: "POST",
          path: new RegExp(
            `^${RegExp.escape(support.pathname.slice(0, boundary))}/api/kernel/set_model_value$`,
          ),
          required: false,
        });
      };
      const retiringModelNotification = await expectRetiringModelNotification();
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
      await recoverRequestAbort(retiringModelNotification);

      const replacedModelNotification = await expectRetiringModelNotification();
      const refreshedProjections = await captureProjectionRefresh(page, diagnostics);
      await writeFile(
        resolve(workspace, "__marimo__/studio/host-save/dashboard/index.html"),
        `<!doctype html><html><head><title>Projections</title></head><body>
        <main id="app-shell"><h1 mo-value="a"></h1>
        <marimo-cell name="cell-1"></marimo-cell>
        <marimo-output value="a"></marimo-output></main></body></html>`,
      );
      await waitForPreview(page);
      const presentation = previewFrame(page);
      await expect(presentation.locator('h1[mo-value="a"]')).toHaveText("42");
      await expect(presentation.locator("marimo-cell")).toContainText("42");
      await expect(presentation.locator("marimo-output")).toContainText("42");
      await recoverProjectionRefresh(refreshedProjections, page);
      await recoverRequestAbort(replacedModelNotification);

      const openedAgain = context.waitForEvent("page");
      await launcher.getByRole("link", { name: "Create a new notebook" }).click();
      const fresh = await openedAgain;
      await expect(fresh.locator("#filename-input input")).toHaveValue("");
      await expect(fresh.locator(".cm-content").first()).toBeEditable();
      await expect(fresh.getByText(/read.only|reader mode/i)).toHaveCount(0);
      await fresh.locator(".cm-content").first().fill('other = "independent"\nother');
      await fresh.locator("[data-cell-id]").first().hover();
      await fresh.locator('button[data-testid="run-button"]:not(:disabled)').first().click();
      await expect(fresh.getByText("'independent'", { exact: true })).toBeVisible();
      await executeCodeMode(
        editorFrame(page),
        "host-save.py",
        connectedSession,
        'assert saved == ["kept"]\nassert "other" not in globals()',
      );

      await editorFrame(page).getByTestId("notebook-menu-dropdown").click();
      await editorFrame(page)
        .getByRole("menuitem", { name: "Restart kernel", exact: true })
        .click();
      const restartedTransports = diagnostics.expectConsole({
        type: "warning",
        text: /^WebSocket closed 1000 MARIMO_SHUTDOWN$/,
        count: 2,
      });
      const restarted = page.waitForEvent("framenavigated", {
        predicate: (frame) =>
          frame.parentFrame() === page.mainFrame() &&
          new URL(frame.url()).pathname.endsWith("/_marimo-studio/editor/"),
      });
      await editorFrame(page).getByRole("button", { name: "Confirm Restart", exact: true }).click();
      await restarted;
      await expect(editorFrame(page).locator(".cm-content").first()).toContainText("saved = []");
      await executeCodeMode(
        editorFrame(page),
        "host-save.py",
        connectedSession,
        "assert saved == []",
      );
      await waitForPreview(page);
      await expect(presentation.locator("marimo-output")).toContainText("42");
      restartedTransports.recovered();

      filenameFallback.recovered();
      dialogDescription.recovered();
      closedLspHealth.recovered();
      closedUsageStats.recovered();
      closedSandboxStatus.recovered();
      closedSandboxRequest.recovered();
      await diagnostics.close();
      diagnosticsClosed = true;
      expect(diagnostics.messages, "unexpected browser diagnostics").toEqual([]);
      await server.close();
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
}
