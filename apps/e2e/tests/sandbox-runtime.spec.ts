import { expect } from "@playwright/test";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";

import { e2eNetwork } from "../scripts/network.ts";
import { previewFrame, waitForViewPreview } from "./fixture.ts";
import { test } from "./network-fixture.ts";
import { closeFailedNotebookServer, startNotebookServer } from "./notebook-server.ts";

// A cold sandbox resolves the notebook environment and Studio's overlay first.
const SANDBOX_TIMEOUT = process.platform === "win32" ? 300_000 : 180_000;

const NOTEBOOK = `# /// script
# requires-python = ">=3.10"
# dependencies = ["marimo"]
# ///

import marimo

app = marimo.App()


@app.cell
def greeting():
    message = "Sandboxed kernels load Studio"
    message
    return (message,)


if __name__ == "__main__":
    app.run()
`;

test("previews a first view from a sandboxed notebook that does not declare Studio", async ({
  browser,
}, testInfo) => {
  test.setTimeout(SANDBOX_TIMEOUT + 60_000);
  const root = await mkdtemp(resolve(tmpdir(), "marimo-studio-sandbox-"));
  const notebook = resolve(root, "notebook.py");
  await writeFile(notebook, NOTEBOOK, "utf-8");
  const server = startNotebookServer({
    authentication: ["--no-token"],
    command: "edit",
    endpoint: e2eNetwork.main.sandbox,
    sandbox: true,
    target: notebook,
  });
  const context = await browser.newContext();
  let closed = false;
  try {
    await server.waitUntilReady(`${server.serverUrl}/`, { timeout: SANDBOX_TIMEOUT });
    const page = await context.newPage();
    await page.goto(`${server.serverUrl}/`, { waitUntil: "domcontentloaded" });
    await page.getByText("Add view", { exact: true }).click({ timeout: SANDBOX_TIMEOUT });
    await page.getByRole("radio", { name: /^HTML document/ }).check();
    await page.getByRole("button", { name: "Create view" }).click();

    await waitForViewPreview(page, "dashboard", "server", SANDBOX_TIMEOUT);
    await expect(previewFrame(page).getByText("Sandboxed kernels load Studio")).toBeVisible();
    await server.close();
    closed = true;
  } finally {
    await context.close();
    if (!closed) {
      const failure = await closeFailedNotebookServer(server);
      if (failure) await testInfo.attach("server cleanup", { body: failure.message });
    }
    await rm(root, { force: true, recursive: true });
  }
});
