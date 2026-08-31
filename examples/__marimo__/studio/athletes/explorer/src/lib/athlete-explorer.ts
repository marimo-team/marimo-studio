import {
  coordinator,
  DuckDBWASMConnector,
  makeClient,
} from "@uwdata/mosaic-core";
import * as vg from "@uwdata/vgplot";

const TABLE_NAME = "athletes";

export type AthleteRow = {
  id: number;
  name: string;
  nationality: string;
  sex: string;
  age: number | null;
  height: number | null;
  weight: number | null;
  sport: string;
  gold: number;
  silver: number;
  bronze: number;
  medal_awards: number;
};

export type AthleteSummary = {
  athletes: number;
  delegations: number;
  medalists: number;
  medalAwards: number;
};

type ExplorerHosts = {
  controls: HTMLDivElement;
  scatter: HTMLDivElement;
  age: HTMLDivElement;
  sports: HTMLDivElement;
  table: HTMLDivElement;
};

type SummaryRow = {
  athletes: number | bigint;
  delegations: number | bigint;
  medalists: number | bigint;
  medal_awards: number | bigint;
};

type QueryResult<Row> = {
  get(index: number): Row | null;
};

export type AthleteExplorer = {
  reset: () => void;
  destroy: () => void;
};

type CreateAthleteExplorerOptions = {
  bytes: Uint8Array;
  hosts: ExplorerHosts;
  isCurrent: () => boolean;
  onSummary: (summary: AthleteSummary) => void;
  onError: (message: string) => void;
};

const number = (value: number | bigint | null | undefined) =>
  Number(value ?? 0);

const labelMenuControls = (host: HTMLElement) => {
  host.querySelectorAll<HTMLElement>(".input").forEach((container, index) => {
    const label = container.querySelector<HTMLLabelElement>("label");
    const control = container.querySelector<
      HTMLInputElement | HTMLSelectElement
    >("input, select");
    if (!label || !control) return;
    control.id ||= `athlete-filter-${index + 1}`;
    label.htmlFor = control.id;
  });
};

const enableKeyboardTableSort = (host: HTMLElement) => {
  const enhanced = new WeakSet<HTMLTableCellElement>();
  const enhance = () => {
    host.querySelectorAll<HTMLTableCellElement>("th").forEach((header) => {
      if (enhanced.has(header)) return;
      enhanced.add(header);
      header.tabIndex = 0;
      const label = header.textContent?.trim().replaceAll("_", " ") ?? "column";
      header.textContent = label;
      header.setAttribute("aria-label", `Sort by ${label}`);
      header.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        header.click();
      });
    });
  };
  const observer = new MutationObserver(enhance);
  observer.observe(host, { childList: true, subtree: true });
  enhance();
  return () => observer.disconnect();
};

const describePlot = (
  plot: HTMLElement,
  label: string,
  description: string,
) => {
  plot.setAttribute("role", "img");
  plot.setAttribute("aria-label", label);
  plot.setAttribute("aria-description", description);
  return plot;
};

const terminateConnector = async (
  connector: DuckDBWASMConnector,
  connection: Awaited<ReturnType<DuckDBWASMConnector["getConnection"]>>,
) => {
  try {
    await connection.close();
  } finally {
    await (await connector.getDuckDB()).terminate();
  }
};

export const createAthleteExplorer = async ({
  bytes,
  hosts,
  isCurrent,
  onSummary,
  onError,
}: CreateAthleteExplorerOptions): Promise<AthleteExplorer | null> => {
  const connector = new DuckDBWASMConnector({ log: false });
  const connection = await connector.getConnection();

  try {
    await connection.insertArrowFromIPCStream(bytes, { name: TABLE_NAME });
  } catch (error) {
    await terminateConnector(connector, connection);
    throw error;
  }

  if (!isCurrent()) {
    await terminateConnector(connector, connection);
    return null;
  }

  const mosaic = coordinator();
  mosaic.clear();
  mosaic.databaseConnector(connector);

  const filters = vg.Selection.crossfilter();
  const controls = [
    vg.menu({
      label: "Sport",
      from: TABLE_NAME,
      column: "sport",
      as: filters,
    }),
    vg.menu({
      label: "Sex",
      from: TABLE_NAME,
      column: "sex",
      as: filters,
    }),
    vg.search({
      label: "Athlete name",
      from: TABLE_NAME,
      column: "name",
      type: "contains",
      as: filters,
    }),
  ];
  hosts.controls.replaceChildren(...controls);
  labelMenuControls(hosts.controls);

  hosts.scatter.replaceChildren(
    describePlot(
      vg.plot(
        vg.dot(vg.from(TABLE_NAME, { filterBy: filters }), {
          x: "weight",
          y: "height",
          fill: "sex",
          r: 3,
          fillOpacity: 0.34,
          strokeOpacity: 0.12,
          tip: true,
        }),
        vg.intervalXY({
          as: filters,
          brush: { fill: "transparent", stroke: "#fc5200", strokeWidth: 1.5 },
        }),
        vg.xyDomain(vg.Fixed),
        vg.colorDomain(["female", "male"]),
        vg.colorRange(["#fc5200", "#39434d"]),
        vg.xLabel("Weight (kg)"),
        vg.yLabel("Height (m)"),
        vg.xGrid(true),
        vg.yGrid(true),
        vg.width(760),
        vg.height(430),
        vg.margins({ top: 20, right: 20, bottom: 45, left: 54 }),
      ),
      "Athlete height and weight scatter plot",
      "Each point is an athlete. Color distinguishes sex. Drag to filter the other charts.",
    ),
  );

  hosts.age.replaceChildren(
    describePlot(
      vg.plot(
        vg.rectY(vg.from(TABLE_NAME, { filterBy: filters }), {
          x: vg.bin("age"),
          y: vg.count(),
          fill: "#39434d",
          insetLeft: 0.75,
          insetRight: 0.75,
          tip: true,
        }),
        vg.intervalX({
          as: filters,
          brush: { fill: "#fc5200", fillOpacity: 0.12, stroke: "#fc5200" },
        }),
        vg.xDomain(vg.Fixed),
        vg.xLabel("Age (years)"),
        vg.yLabel("Athletes"),
        vg.yGrid(true),
        vg.width(430),
        vg.height(260),
        vg.margins({ top: 12, right: 16, bottom: 44, left: 48 }),
      ),
      "Athlete age histogram",
      "Drag across an age range to filter the roster.",
    ),
  );

  hosts.sports.replaceChildren(
    describePlot(
      vg.plot(
        vg.barX(vg.from(TABLE_NAME, { filterBy: filters }), {
          x: vg.count(),
          y: "sport",
          fill: "#fc5200",
          fillOpacity: 0.82,
          sort: { y: "-x", limit: 10 },
          tip: true,
        }),
        vg.toggleY({ as: filters }),
        vg.xLabel("Athletes"),
        vg.yLabel(null),
        vg.xGrid(true),
        vg.width(430),
        vg.height(300),
        vg.margins({ top: 12, right: 16, bottom: 44, left: 112 }),
      ),
      "Largest sports by athlete count",
      "Select a bar to filter the other views to one sport.",
    ),
  );

  hosts.table.replaceChildren(
    vg.table({
      from: TABLE_NAME,
      filterBy: filters,
      columns: [
        "name",
        "nationality",
        "sport",
        "age",
        "height",
        "weight",
        "medal_awards",
      ],
      format: {
        age: (value: number | null) =>
          value == null ? "" : Math.round(value).toString(),
        height: (value: number | null) => value == null ? "" : value.toFixed(2),
        weight: (value: number | null) => value == null ? "" : value.toFixed(1),
      },
      width: {
        name: 190,
        nationality: 92,
        sport: 150,
        age: 56,
        height: 68,
        weight: 68,
        medal_awards: 92,
      },
      height: 360,
      rowBatch: 50,
    }),
  );
  const stopKeyboardTableSort = enableKeyboardTableSort(hosts.table);

  makeClient({
    coordinator: mosaic,
    selection: filters,
    query: (filter) =>
      vg.Query.from(TABLE_NAME)
        .select({
          athletes: vg.count(),
          delegations: vg.sql`COUNT(DISTINCT nationality)`,
          medalists: vg.sql`COUNT(*) FILTER (WHERE medal_awards > 0)`,
          medal_awards: vg.sum("medal_awards"),
        })
        .where(filter),
    queryResult: (data) => {
      const row = (data as QueryResult<SummaryRow>).get(0);
      if (!row) return;
      onSummary({
        athletes: number(row.athletes),
        delegations: number(row.delegations),
        medalists: number(row.medalists),
        medalAwards: number(row.medal_awards),
      });
    },
    queryError: () => onError("The roster query failed."),
  });

  let destroyed = false;
  return {
    reset: () => filters.reset(),
    destroy: () => {
      if (destroyed) return;
      destroyed = true;
      stopKeyboardTableSort();
      mosaic.clear();
      Object.values(hosts).forEach((host) => host.replaceChildren());
      void terminateConnector(connector, connection).catch(() => {});
    },
  };
};
