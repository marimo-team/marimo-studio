<script lang="ts">
import {
  type AthleteExplorer,
  type AthleteRow,
  type AthleteSummary,
  createAthleteExplorer,
} from "./lib/athlete-explorer.ts";
import {
  getMarimoDataSource,
  isMarimoTable,
  type MarimoTable,
  observeMarimoValue,
} from "./lib/marimo-value.ts";

type LoadState = "waiting" | "loading" | "ready" | "error";
let athleteFacts = $state<MarimoTable<AthleteRow>>();
let loadState = $state<LoadState>("waiting");
let errorMessage = $state("");
let summary = $state<AthleteSummary>();
let controlsHost = $state<HTMLDivElement>();
let scatterHost = $state<HTMLDivElement>();
let ageHost = $state<HTMLDivElement>();
let sportsHost = $state<HTMLDivElement>();
let tableHost = $state<HTMLDivElement>();
let resetFilters = $state<() => void>(() => {});
let loadRevision = 0;

const athleteColumns = [
  "id",
  "name",
  "nationality",
  "sex",
  "age",
  "height",
  "weight",
  "sport",
  "gold",
  "silver",
  "bronze",
  "medal_awards",
] as const;

const isAthleteTable = (value: unknown): value is MarimoTable<AthleteRow> =>
  isMarimoTable(value) &&
  athleteColumns.every((name) => value.names.includes(name));

const formatCount = (value: number | undefined) =>
  value === undefined ? "…" : value.toLocaleString("en-US");

$effect(() => {
  const table = athleteFacts;
  const hosts = {
    controls: controlsHost,
    scatter: scatterHost,
    age: ageHost,
    sports: sportsHost,
    table: tableHost,
  };

  if (!table || Object.values(hosts).some((host) => host === undefined)) {
    return;
  }

  const source = getMarimoDataSource(table);
  if (source?.codec !== "arrow-ipc-v1") {
    loadState = "error";
    errorMessage = "The athlete roster could not be loaded.";
    return;
  }

  const revision = ++loadRevision;
  let explorer: AthleteExplorer | undefined;
  loadState = "loading";
  errorMessage = "";
  summary = undefined;

  void createAthleteExplorer({
    bytes: source.bytes.slice(),
    hosts: {
      controls: hosts.controls!,
      scatter: hosts.scatter!,
      age: hosts.age!,
      sports: hosts.sports!,
      table: hosts.table!,
    },
    isCurrent: () => revision === loadRevision,
    onError: (message) => {
      if (revision === loadRevision) {
        loadState = "error";
        errorMessage = message;
      }
    },
    onSummary: (next) => {
      if (revision === loadRevision) {
        summary = next;
      }
    },
  })
    .then((next) => {
      if (!next) return;
      if (revision !== loadRevision) {
        next.destroy();
        return;
      }
      explorer = next;
      resetFilters = next.reset;
      loadState = "ready";
    })
    .catch(() => {
      if (revision !== loadRevision) return;
      loadState = "error";
      errorMessage = "The athlete roster could not be loaded.";
    });

  return () => {
    loadRevision += 1;
    explorer?.destroy();
    resetFilters = () => {};
  };
});
</script>

<div class="page" data-load-state={loadState}>
  <nav aria-label="Athlete views">
    <a href="../overview/index.html">Overview</a>
    <a href="../explorer/index.html" aria-current="page">Explorer</a>
    <a href="../field/index.html">Field</a>
  </nav>

  <header class="hero">
    <div>
      <p class="eyebrow">Rio de Janeiro · 2016</p>
      <h1>Athlete field book</h1>
    </div>
    <p class="lede">
      Explore body profiles, age, participation, and athlete medal awards across
      the complete Olympic roster.
    </p>
  </header>

  <section class="scoreboard" aria-label="Filtered roster summary"
    aria-live="polite">
    <article class="score">
      <span>Athletes</span>
      <strong>{formatCount(summary?.athletes)}</strong>
    </article>
    <article class="score">
      <span>Delegations</span>
      <strong>{formatCount(summary?.delegations)}</strong>
    </article>
    <article class="score">
      <span>Medalists</span>
      <strong>{formatCount(summary?.medalists)}</strong>
    </article>
    <article class="score score-signal">
      <span>Medal awards</span>
      <strong>{formatCount(summary?.medalAwards)}</strong>
    </article>
  </section>

  <div class="workspace">
    <aside class="filter-panel" aria-labelledby="filters-title">
      <p class="eyebrow">Roster filters</p>
      <h2 id="filters-title">Narrow the roster</h2>
      <p>
        Choose a sport or sex, search by name, or brush a chart. The roster,
        distributions, and headline totals update together.
      </p>
      <div
        class="mosaic-controls"
        bind:this={controlsHost}
        aria-busy={loadState === "loading"}
      ></div>
      <button
        class="reset-button"
        type="button"
        onclick={() => resetFilters()}
        disabled={loadState !== "ready"}
      >
        Reset all filters
      </button>
    </aside>

    <main class="analysis" aria-label="Athlete analysis">
      {#if loadState === "waiting" || loadState === "loading"}
        <p class="status status-loading" role="status">
          <span class="status-pulse" aria-hidden="true"><i></i><i></i><i></i></span>
          Loading athlete roster…
        </p>
      {:else if loadState === "error"}
        <p class="status status-error" role="alert">{errorMessage}</p>
      {/if}

      <article class="panel profile-panel" aria-labelledby="profile-title">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">Body profile</p>
            <h2 id="profile-title">Height and weight</h2>
          </div>
          <p>Drag across the field to compare a cohort.</p>
        </div>
        <div class="mosaic-host" bind:this={scatterHost}></div>
      </article>

      <div class="supporting-grid">
        <article class="panel" aria-labelledby="age-title">
          <div class="panel-heading compact">
            <div>
              <p class="eyebrow">Distribution</p>
              <h2 id="age-title">Age at opening</h2>
            </div>
            <p>Brush a range.</p>
          </div>
          <div class="mosaic-host" bind:this={ageHost}></div>
        </article>

        <article class="panel" aria-labelledby="sports-title">
          <div class="panel-heading compact">
            <div>
              <p class="eyebrow">Participation</p>
              <h2 id="sports-title">Athletes by sport</h2>
            </div>
            <p>Select a bar.</p>
          </div>
          <div class="mosaic-host" bind:this={sportsHost}></div>
        </article>
      </div>

      <article class="panel table-panel" aria-labelledby="roster-title">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">Roster detail</p>
            <h2 id="roster-title">Matching athletes</h2>
          </div>
          <p>Scroll for more records. Select a header to sort.</p>
        </div>
        <div class="mosaic-table" bind:this={tableHost}></div>
      </article>
    </main>
  </div>

  <footer>
    <a href="https://datahub.io/core/rio2016" target="_blank" rel="noreferrer">
      Rio 2016 athlete data
    </a>
    · <a href="https://opendatacommons.org/licenses/pddl/1-0/" target="_blank" rel="noreferrer">ODC-PDDL 1.0</a>
  </footer>
</div>

<span
  aria-hidden="true"
  hidden
  mo-value="athlete_facts"
  use:observeMarimoValue={{
    selector: "athlete_facts",
    onValue: (value: unknown) => {
      if (isAthleteTable(value)) {
        athleteFacts = value;
        return;
      }
      loadState = "error";
      errorMessage = "The athlete roster could not be loaded.";
    },
    onError: () => {
      loadState = "error";
      errorMessage = "The athlete roster could not be loaded.";
    },
  }}
></span>
