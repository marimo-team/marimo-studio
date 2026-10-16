import { projectionDiagnosticSchema } from "@marimo-studio/protocol/runtime-config";
import { expect as playwrightExpect, type Page } from "@playwright/test";

import { runCellShortcut } from "./authoring-test-support.ts";
import {
  captureProjectionRefresh,
  editorFrame,
  expect,
  observeBrowserContext,
  previewFrame,
  readWorkspaceFile,
  recoverProjectionRefresh,
  restoreWorkspace,
  studioEntryUrl,
  test,
  waitForPreview,
  workspaceNotebookPath,
} from "./fixture.ts";
import { test as playwrightTest } from "./network-fixture.ts";
import { installPinnedPyodideAssets } from "./pyodide-assets.ts";
import { editServerUrl, startEditServer } from "./recovery-support.ts";

const originalMetricSource =
  'metric = scale.value * 21\nresponsive_value = "responsive" * 80\nmetric';

declare global {
  var __studioWebSocketObservations: WebSocketObservation[] | undefined;
}

interface WebSocketObservation {
  documentUrl: string;
  socketUrl: string;
  opened?: boolean;
  closeCode?: number;
  closeReason?: string;
}

const replaceMetricCell = async (page: Page, source: string) => {
  const cell = editorFrame(page).locator('[data-cell-name="metric"]');
  const runtime = cell.locator("..");
  const editor = cell.getByRole("textbox");
  await editor.fill(source);
  await Promise.all([
    page.waitForResponse((response) => {
      const request = response.request();
      return (
        request.method() === "POST" &&
        new URL(response.url()).pathname.endsWith("/api/kernel/run") &&
        response.ok()
      );
    }),
    editor.press(runCellShortcut),
  ]);
  await expect(runtime).toHaveAttribute("data-status", "idle");
};

const waitForMetricSource = () =>
  expect
    .poll(async () => {
      const source = await readWorkspaceFile(workspaceNotebookPath);
      return source.includes("metric = scale.value * 21") && !source.includes("replacement =");
    })
    .toBe(true);

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

const isWorkspaceEventSocket = (observation: WebSocketObservation): boolean =>
  new URL(observation.socketUrl).pathname === "/_marimo-studio/dev/events";

const workspaceEventSockets = async (page: Page): Promise<WebSocketObservation[]> =>
  (await webSocketObservations(page)).filter(isWorkspaceEventSocket);

playwrightTest(
  "a fresh Studio tab starts after the server restarts with a stale tab open",
  async ({ context, page }, testInfo) => {
    await restoreWorkspace();
    await installPinnedPyodideAssets(context);
    await context.addInitScript(() => {
      const NativeWebSocket = globalThis.WebSocket;
      globalThis.__studioWebSocketObservations = [];
      globalThis.WebSocket = class extends NativeWebSocket {
        constructor(url: string | URL, protocols: string | string[] = []) {
          super(url, protocols);
          const observation: WebSocketObservation = {
            documentUrl: globalThis.location.href,
            socketUrl: this.url,
          };
          globalThis.__studioWebSocketObservations?.push(observation);
          this.addEventListener("open", () => {
            observation.opened = true;
          });
          this.addEventListener("close", (event) => {
            observation.closeCode = event.code;
            observation.closeReason = event.reason;
          });
        }
      };
    });
    const servers: Array<ReturnType<typeof startEditServer>> = [];
    let server = startEditServer();
    servers.push(server);
    let fresh: Page | undefined;
    const diagnostics = observeBrowserContext(context);
    let diagnosticsClosed = false;

    try {
      await server.waitUntilReady(editServerUrl());
      await page.goto(editServerUrl());
      await waitForPreview(page);
      await playwrightExpect
        .poll(async () =>
          (await workspaceEventSockets(page)).map((observation) => observation.opened === true),
        )
        .toEqual([true]);
      await playwrightExpect
        .poll(async () => (await webSocketObservations(page)).some(isEditorSocket))
        .toBe(true);

      const openSockets = (await webSocketObservations(page)).filter(
        (observation) =>
          observation.closeCode === undefined && !isWorkspaceEventSocket(observation),
      );
      playwrightExpect(openSockets.length).toBeGreaterThan(0);
      // The stale tab reconnects while the server restarts.
      const refusedReconnects = diagnostics.expectConsole({
        type: "error",
        text: /^WebSocket connection to '[^']+\/_marimo-studio\/dev\/events\?[^']*' failed: /,
        count: 5,
        required: false,
      });
      const shutdownWarnings = diagnostics.expectConsole({
        type: "warning",
        text: /^WebSocket closed 1000 MARIMO_SHUTDOWN$/,
        count: openSockets.length,
      });

      await server.close();
      server = startEditServer();
      servers.push(server);
      await server.waitUntilReady(editServerUrl());
      // The stale tab reconnects with its old event URL, and the restarted
      // server closes that socket as retired: 4000 + 204.
      await playwrightExpect
        .poll(async () =>
          (await workspaceEventSockets(page)).some((observation) => observation.closeCode === 4204),
        )
        .toBe(true);
      await playwrightExpect
        .poll(async () =>
          (await webSocketObservations(page)).some(
            (observation) =>
              isEditorSocket(observation) &&
              observation.closeCode !== undefined &&
              observation.closeCode !== 1006,
          ),
        )
        .toBe(true);

      const current = await context.newPage();
      fresh = current;
      await current.goto(editServerUrl());
      const preview = await waitForPreview(current);
      await playwrightExpect(preview.getByText("Projected total:")).toBeVisible();
      await playwrightExpect
        .poll(async () => (await workspaceEventSockets(current)).length)
        .toBe(1);
      shutdownWarnings.recovered();
      refusedReconnects.recovered();
      await diagnostics.close();
      diagnosticsClosed = true;
      playwrightExpect(diagnostics.messages, "unexpected browser diagnostics").toEqual([]);
    } catch (error) {
      await Promise.all(
        servers.map((candidate, index) =>
          testInfo.attach(`recovery-server-${index + 1}`, {
            body: Buffer.from(candidate.output()),
            contentType: "text/plain",
          }),
        ),
      );
      throw error;
    } finally {
      if (!diagnosticsClosed) {
        await diagnostics.close();
      }
      await fresh?.close();
      await server.close();
      await restoreWorkspace();
    }
  },
);

test("restores value and function output hosts after their notebook values return", async ({
  browserDiagnostics,
  page,
}) => {
  await page.goto(studioEntryUrl);
  const preview = await waitForPreview(page);
  const value = preview.locator('[mo-value="metric"]');
  const peerOutput = preview.locator('marimo-output[value="rich_table"]');
  const currentViewRevision = () =>
    preview.locator("html").evaluate(() => globalThis.marimoStudio.identity().revision);
  const initial = await value.textContent();
  expect(initial).toMatch(/^\d+$/);
  await expect(peerOutput).toHaveAttribute("data-state", "ready");
  let restored = false;

  try {
    const initialViewRevision = await currentViewRevision();
    const missingMetricRefresh = await captureProjectionRefresh(page, browserDiagnostics);
    await replaceMetricCell(page, "replacement = scale.value * 21\nreplacement");
    await expect.poll(currentViewRevision).not.toBe(initialViewRevision);

    await expect(value).toHaveAttribute("data-state", "error");
    const diagnostics: readonly unknown[] = await preview
      .locator("html")
      .evaluate(() => globalThis.marimoStudio.diagnostics());
    const metricError = diagnostics
      .map((diagnostic) => projectionDiagnosticSchema.safeParse(diagnostic))
      .find(
        (diagnostic) =>
          diagnostic.success &&
          diagnostic.data.code === "projection-value-variable-not-found" &&
          diagnostic.data.projection === "value" &&
          diagnostic.data.target === "metric",
      )?.data;
    expect(metricError, JSON.stringify(diagnostics)).toMatchObject({ severity: "error" });
    await expect(value).toHaveText("Unavailable");
    await expect(value).toHaveAccessibleName(/'metric' does not resolve/);
    await expect(value).toHaveAttribute("title", /'metric' does not resolve/);
    missingMetricRefresh.capture.terminalizeValues(["metric"]);
    await recoverProjectionRefresh(missingMetricRefresh, page);
    const missingMetricRevision = await currentViewRevision();
    const restoredMetricRefresh = await captureProjectionRefresh(page, browserDiagnostics);
    await replaceMetricCell(page, originalMetricSource);
    await waitForMetricSource();
    await expect.poll(currentViewRevision).not.toBe(missingMetricRevision);
    await waitForPreview(page);
    await expect(value).toHaveAttribute("data-state", "ready");
    await expect(peerOutput).toHaveAttribute("data-state", "ready");
    restored = true;
    await expect(value).toHaveText(initial ?? "");
    await expect(previewFrame(page).locator("html")).toHaveAttribute(
      "data-marimo-studio-state",
      "ready",
    );
    await recoverProjectionRefresh(restoredMetricRefresh, page);
  } finally {
    if (!restored) {
      const source = await readWorkspaceFile(workspaceNotebookPath);
      const replacingSource = source.includes("replacement =");
      const currentRevision = await currentViewRevision();
      await replaceMetricCell(page, originalMetricSource);
      await waitForMetricSource();
      if (replacingSource) {
        await expect.poll(currentViewRevision).not.toBe(currentRevision);
      }
      await waitForPreview(page);
      await expect(value).toHaveAttribute("data-state", "ready");
    }
  }
});
