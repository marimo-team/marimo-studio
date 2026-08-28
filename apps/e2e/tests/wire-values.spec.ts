import {
  dashboardHtmlPath,
  expect,
  labeledSlider,
  type presentationFrame,
  readWorkspaceFile,
  studioEntryUrl,
  test,
  waitForPreview,
  workspaceNotebookPath,
  writeWorkspaceFile,
} from "./fixture.ts";

test.describe.configure({ timeout: 150_000 });

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
        '<span id="projected-table" hidden mo-value="dataframe_value"></span>\n' +
          '      <output id="projected-table-summary"></output>\n' +
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
      const dataSource = Symbol.for("marimo-studio.data-source");

      const renderTable = (table) => {
        const source = table[dataSource];
        const first = table.get(0);
        const second = table.get(1);
        tableSummary.textContent = \`${"${table.numRows}"} rows × ${"${table.numCols}"} columns\`;
        tableSummary.dataset.codec = source.codec;
        tableSummary.dataset.isTable = String(
          Object.prototype.toString.call(table) === "[object Table]",
        );
        tableSummary.dataset.byteLength = String(source.bytes.byteLength);
        tableSummary.dataset.fingerprint = source.fingerprint;
        tableSummary.dataset.firstRegion = first.region;
        tableSummary.dataset.firstRevenue = String(first.revenue);
        tableSummary.dataset.nullRevenue = String(second.revenue === null);
        tableSummary.dataset.firstActive = String(first.active);
        tableSummary.dataset.firstSegment = first.segment;
        tableSummary.dataset.payloadLength = String(first.payload.byteLength);
      };

      const renderEmptyTable = (table) => {
        emptySummary.textContent = \`${"${table.numRows}"} rows × ${"${table.numCols}"} columns\`;
        emptySummary.dataset.updateCount = String(
          Number(emptySummary.dataset.updateCount ?? 0) + 1,
        );
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
  expectedRevenue?: number,
) => {
  const summary = preview.locator("#projected-table-summary");
  await expect(summary).toHaveText("2 rows × 6 columns");
  await expect(summary).toHaveAttribute("data-codec", "arrow-ipc-v1");
  await expect(summary).toHaveAttribute("data-is-table", "true");
  await expect(summary).toHaveAttribute("data-first-region", "emea");
  await expect(summary).toHaveAttribute("data-null-revenue", "true");
  await expect(summary).toHaveAttribute("data-first-active", "true");
  await expect(summary).toHaveAttribute("data-first-segment", "retail");
  await expect(summary).toHaveAttribute("data-payload-length", "2");
  if (expectedRevenue !== undefined) {
    await expect(summary).toHaveAttribute("data-first-revenue", String(expectedRevenue));
  }
  await expect
    .poll(async () => Number((await summary.getAttribute("data-byte-length")) ?? 0))
    .toBeGreaterThan(0);
  return summary;
};

const expectEmptyDataframe = async (preview: ReturnType<typeof presentationFrame>) => {
  const summary = preview.locator("#empty-table-summary");
  await expect(summary).toHaveText("0 rows × 2 columns");
  await expect(summary).toHaveAttribute("data-update-count", "1");
  return summary;
};

test("delivers and refreshes dataframe values in Server and WebAssembly runtimes", async ({
  page,
}) => {
  await installProjectedDataframe();
  await page.goto(studioEntryUrl);
  const server = await waitForPreview(page);
  const serverSummary = await expectProjectedDataframe(server, 42);
  const serverEmptySummary = await expectEmptyDataframe(server);
  const serverFingerprint = await serverSummary.getAttribute("data-fingerprint");
  await labeledSlider(server.locator('marimo-cell[name="controls"]'), /^Scale/).press("End");
  await expect(serverSummary).toHaveAttribute("data-first-revenue", "63");
  await expect
    .poll(() => serverSummary.getAttribute("data-fingerprint"))
    .not.toBe(serverFingerprint);
  await expect(serverEmptySummary).toHaveAttribute("data-update-count", "1");

  await page.getByLabel("Python preview runtime").click();
  await page.getByRole("button", { name: /Browser/ }).click();
  const wasm = await waitForPreview(page, "wasm");
  const wasmSummary = await expectProjectedDataframe(wasm);
  const wasmEmptySummary = await expectEmptyDataframe(wasm);
  const wasmFingerprint = await wasmSummary.getAttribute("data-fingerprint");
  await labeledSlider(wasm.locator('marimo-cell[name="controls"]'), /^Scale/).press("Home");
  await expect(wasmSummary).toHaveAttribute("data-first-revenue", "21");
  await expect.poll(() => wasmSummary.getAttribute("data-fingerprint")).not.toBe(wasmFingerprint);
  await expect(wasmEmptySummary).toHaveAttribute("data-update-count", "1");
});
