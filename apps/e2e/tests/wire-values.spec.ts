import {
  dashboardHtmlPath,
  expect,
  labeledSlider,
  type presentationFrame,
  readWorkspaceFile,
  studioEntryUrl,
  test,
  WASM_PREVIEW_TIMEOUT,
  waitForPreview,
  workspaceNotebookPath,
  writeWorkspaceFile,
} from "./fixture.ts";

test.describe.configure({ timeout: 210_000 });

const installProjectedDataframe = async () => {
  const notebook = await readWorkspaceFile(workspaceNotebookPath);
  await writeWorkspaceFile(
    workspaceNotebookPath,
    notebook
      .replace('#     "marimo-studio"\n', '#     "marimo-studio",\n#     "polars==1.43.2"\n')
      .replace(
        "\n\n@app.cell\ndef slow_metric",
        `

@app.cell
def dataframe_value(scale):
    from datetime import date

    import polars as pl

    dataframe_value = pl.DataFrame(
        {
            "region": ["emea", "apac"],
            "revenue": [scale.value * 21, None],
            "active": [True, False],
            "segment": pl.Series(["retail", "enterprise"], dtype=pl.Categorical),
            "event_date": [date(2026, 8, 28), date(2026, 8, 29)],
            "payload": [b"\\x01\\x02", None],
        }
    )
    empty_dataframe = pl.DataFrame(schema={"value": pl.Int64, "label": pl.String})
    return dataframe_value, empty_dataframe


@app.cell
def slow_metric`,
      ),
  );

  const source = await readWorkspaceFile(dashboardHtmlPath);
  await writeWorkspaceFile(
    dashboardHtmlPath,
    source
      .replace(
        '<marimo-output id="rich-summary-output"',
        '<span id="projected-table" hidden style="display:block" mo-value="dataframe_value"></span>\n' +
          '      <output id="projected-table-summary" data-marimo-sources="projected-table"></output>\n' +
          '      <span id="empty-table" hidden mo-value="empty_dataframe"></span>\n' +
          '      <output id="empty-table-summary"></output>\n' +
          '      <marimo-output id="rich-summary-output"',
      )
      .replace(
        "</body>",
        `  <script type="module">
      const tableHost = document.querySelector("#projected-table");
      const tableSummary = document.querySelector("#projected-table-summary");
      const emptyHost = document.querySelector("#empty-table");
      const emptySummary = document.querySelector("#empty-table-summary");
      const renderTable = (table) => {
        const first = table.get(0);
        const second = table.get(1);
        tableSummary.textContent = [
          \`${"${table.numRows}"} rows × ${"${table.numCols}"} columns\`,
          \`${"${first.region}"}: ${"${first.revenue}"}\`,
          \`missing: ${"${second.revenue === null}"}\`,
          \`active: ${"${first.active}"}\`,
          \`segment: ${"${first.segment}"}\`,
          \`payload: ${"${first.payload.byteLength}"} bytes\`,
        ].join(" | ");
      };

      const renderEmptyTable = (table) => {
        emptySummary.textContent = \`${"${table.numRows}"} rows × ${"${table.numCols}"} columns\`;
      };

      tableHost.addEventListener("marimo-value-updated", (event) => {
        renderTable(event.detail.value);
      });
      if (tableHost.marimoValue !== undefined) {
        renderTable(tableHost.marimoValue);
      }
      emptyHost.addEventListener("marimo-value-updated", (event) => {
        renderEmptyTable(event.detail.value);
      });
      if (emptyHost.marimoValue !== undefined) {
        renderEmptyTable(emptyHost.marimoValue);
      }
    </script>
  </body>`,
      ),
  );
};

const expectProjectedDataframe = async (
  preview: ReturnType<typeof presentationFrame>,
  expectedRevenue: number,
) => {
  const summary = preview.locator("#projected-table-summary");
  await expect(summary).toHaveText(
    `2 rows × 6 columns | emea: ${expectedRevenue} | missing: true | ` +
      "active: true | segment: retail | payload: 2 bytes",
  );
  const source = preview.locator("#projected-table");
  await expect(source).toBeHidden();
  await expect(source).toHaveAttribute("data-runtime-cell-id", /.+/);
  await expect(source).toHaveAttribute("data-marimo-lens-label", "dataframe_value");
  await expect(source).toHaveAttribute("data-marimo-lens-detail", "Value · dataframe_value");
};

const expectEmptyDataframe = async (preview: ReturnType<typeof presentationFrame>) => {
  const summary = preview.locator("#empty-table-summary");
  await expect(summary).toHaveText("0 rows × 2 columns");
};

test("delivers and refreshes dataframe values in Server and WebAssembly runtimes", async ({
  page,
}) => {
  await installProjectedDataframe();
  await page.goto(studioEntryUrl);
  const server = await waitForPreview(page);
  await expectProjectedDataframe(server, 42);
  await expectEmptyDataframe(server);
  await labeledSlider(server.locator('marimo-cell[name="controls"]'), /^Scale/).press("End");
  await expectProjectedDataframe(server, 63);

  await page.getByLabel("Python preview runtime").click();
  await page.getByRole("button", { name: /Browser/ }).click();
  const wasm = await waitForPreview(page, "wasm", WASM_PREVIEW_TIMEOUT);
  await expectProjectedDataframe(wasm, 63);
  await expectEmptyDataframe(wasm);
  await labeledSlider(wasm.locator('marimo-cell[name="controls"]'), /^Scale/).press("Home");
  await expectProjectedDataframe(wasm, 21);
});
