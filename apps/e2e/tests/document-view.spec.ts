import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import type { StudioCli } from "./studio-cli.ts";

import { workspaceDirectory } from "../scripts/paths.ts";
import {
  editorSlider,
  expect,
  previewFrame,
  selectWorkspaceMode,
  test,
  WASM_PREVIEW_TIMEOUT,
  waitForPreview,
  workspaceNotebookPath,
  writeWorkspaceFile,
} from "./fixture.ts";

const reportSource = resolve(workspaceDirectory, "__marimo__/studio/notebook/report/main.typ");

test("renders a Typst document again when a notebook value changes", async ({
  page,
  studioCli,
}) => {
  test.setTimeout(180_000);
  await studioCli.addWorkspaceView(workspaceNotebookPath, "report", "marimo-studio/typst:default");
  await writeWorkspaceFile(
    reportSource,
    [
      '#import "marimo.typ": marimo_value',
      "#set page(width: 12cm, height: auto)",
      '= Metric is #marimo_value("metric", default: "pending")',
      "",
    ].join("\n"),
  );
  await studioCli.buildWorkspaceView("report");

  await page.goto("/studio/report/?file=notebook.py");
  const preview = await waitForPreview(page);
  const viewer = preview.locator("marimo-document");
  await expect(viewer).toHaveAttribute("data-state", "ready");
  await expect(viewer.locator(".textLayer")).toContainText("Metric is 42");
  await expect(viewer.getByRole("link", { name: "Download" })).toHaveAttribute(
    "download",
    "main.pdf",
  );

  await selectWorkspaceMode(page, "Notebook");
  await editorSlider(page).press("End");
  await selectWorkspaceMode(page, "Develop");
  await waitForPreview(page);
  await expect(viewer.locator(".textLayer")).toContainText("Metric is 63");
  await expect(viewer).toHaveAttribute("data-state", "ready");
});

const chartCell = [
  "@app.cell",
  "def chart(metric):",
  "    from matplotlib.figure import Figure",
  "",
  "    chart = Figure(figsize=(4, 2))",
  "    chart.subplots().bar(['metric'], [metric])",
  '    chart.suptitle(f"Chart {metric}")',
  "    return (chart,)",
  "",
  "",
  'if __name__ == "__main__":',
].join("\n");

const createChartReport = async (studioCli: StudioCli) => {
  const notebook = await readFile(workspaceNotebookPath, "utf8");
  await writeWorkspaceFile(
    workspaceNotebookPath,
    notebook.replace('if __name__ == "__main__":', chartCell),
  );
  await studioCli.addWorkspaceView(workspaceNotebookPath, "report", "marimo-studio/typst:default");
  await writeWorkspaceFile(
    reportSource,
    [
      '#import "marimo.typ": marimo_output',
      "#set page(width: 12cm, height: auto)",
      '#marimo_output("chart", width: 10cm, default: [Figure pending])',
      "",
    ].join("\n"),
  );
  await studioCli.buildWorkspaceView("report");
};

test("embeds a notebook figure in a Typst document and renders it again when it changes", async ({
  page,
  studioCli,
}) => {
  test.setTimeout(180_000);
  await createChartReport(studioCli);

  await page.goto("/studio/report/?file=notebook.py");
  const preview = await waitForPreview(page);
  const viewer = preview.locator("marimo-document");
  await expect(viewer).toHaveAttribute("data-state", "ready");
  // Studio renders the figure as a PDF with real text, so pdf.js extracts its
  // title only when the document embeds a vector figure. The notebook keeps
  // its default PNG output.
  await expect(viewer.locator(".textLayer")).toContainText("Chart 42");

  await selectWorkspaceMode(page, "Notebook");
  await editorSlider(page).press("End");
  await selectWorkspaceMode(page, "Develop");
  await waitForPreview(page);
  await expect(viewer.locator(".textLayer")).toContainText("Chart 63");
  await expect(viewer).toHaveAttribute("data-state", "ready");
});

test("embeds a notebook figure in a Typst document in the browser runtime", async ({
  page,
  studioCli,
}) => {
  test.setTimeout(300_000);
  await createChartReport(studioCli);

  await page.goto("/studio/report/?file=notebook.py");
  await waitForPreview(page);
  await page.getByLabel(/preview runtime$/).click();
  await page.getByRole("button", { name: /Browser/ }).click();
  const preview = await waitForPreview(page, "wasm", WASM_PREVIEW_TIMEOUT);
  const viewer = preview.locator("marimo-document");
  await expect(viewer.locator(".textLayer")).toContainText("Chart 42", {
    timeout: WASM_PREVIEW_TIMEOUT,
  });
  await expect(viewer).toHaveAttribute("data-state", "ready");
});

// A named cell whose output is the chart figure, as marimo shows it.
const chartViewCell = [
  "@app.cell",
  "def chart_view(chart):",
  "    chart",
  "    return",
  "",
  "",
  'if __name__ == "__main__":',
].join("\n");

const createCellReport = async (studioCli: StudioCli) => {
  const notebook = await readFile(workspaceNotebookPath, "utf8");
  await writeWorkspaceFile(
    workspaceNotebookPath,
    notebook.replace(
      'if __name__ == "__main__":',
      chartCell.replace('if __name__ == "__main__":', chartViewCell),
    ),
  );
  await studioCli.addWorkspaceView(workspaceNotebookPath, "report", "marimo-studio/typst:default");
  await writeWorkspaceFile(
    reportSource,
    [
      '#import "marimo.typ": marimo_cell',
      "#set page(width: 12cm, height: auto)",
      '#let view = marimo_cell("chart_view", width: 10cm)',
      "#if view == none [Cell pending] else [Cell placed #view]",
      "",
    ].join("\n"),
  );
  await studioCli.buildWorkspaceView("report");
};

test("places a notebook cell's figure in a Typst document", async ({ page, studioCli }) => {
  test.setTimeout(180_000);
  await createCellReport(studioCli);

  await page.goto("/studio/report/?file=notebook.py");
  const preview = await waitForPreview(page);
  const viewer = preview.locator("marimo-document");
  await expect(viewer.locator(".textLayer")).toContainText("Cell placed");
  await expect(viewer).toHaveAttribute("data-state", "ready");
});

test("places a notebook cell's figure in a Typst document in the browser runtime", async ({
  page,
  studioCli,
  browserDiagnostics,
}) => {
  test.setTimeout(300_000);
  // marimo imports its optional widget packages when a cell shows a
  // matplotlib figure. The browser tests serve only the prepared Pyodide
  // packages, so those imports fail without affecting the figure.
  const widgetPackages = [
    browserDiagnostics.expectConsole({
      text: /^The following error occurred while loading (?:anywidget|ipywidgets|comm|jupyterlab_widgets|widgetsnbextension|psygnal):$/,
      count: 6,
      required: false,
    }),
    browserDiagnostics.expectConsole({ text: /^Failed to fetch$/, count: 6, required: false }),
  ];
  await createCellReport(studioCli);

  await page.goto("/studio/report/?file=notebook.py");
  await waitForPreview(page);
  await page.getByLabel(/preview runtime$/).click();
  await page.getByRole("button", { name: /Browser/ }).click();
  const preview = await waitForPreview(page, "wasm", WASM_PREVIEW_TIMEOUT);
  const viewer = preview.locator("marimo-document");
  await expect(viewer.locator(".textLayer")).toContainText("Cell placed", {
    timeout: WASM_PREVIEW_TIMEOUT,
  });
  await expect(viewer).toHaveAttribute("data-state", "ready");
  widgetPackages.forEach((expectation) => expectation.recovered());
});

test("shows the template default for an output without an image form", async ({
  page,
  studioCli,
}) => {
  test.setTimeout(180_000);
  await studioCli.addWorkspaceView(workspaceNotebookPath, "report", "marimo-studio/typst:default");
  await writeWorkspaceFile(
    reportSource,
    [
      '#import "marimo.typ": marimo_output',
      "#set page(width: 12cm, height: auto)",
      '#marimo_output("metric", default: [Figure pending])',
      "",
    ].join("\n"),
  );
  await studioCli.buildWorkspaceView("report");

  await page.goto("/studio/report/?file=notebook.py");
  const viewer = previewFrame(page).locator("marimo-document");
  await expect(viewer).toHaveAttribute("data-state", "ready", { timeout: 60_000 });
  await expect(viewer.locator(".textLayer")).toContainText("Figure pending");
  await expect(viewer.getByRole("status")).toContainText(
    /Showing the default for metric \(.*no representation as application\/pdf/,
  );
});
