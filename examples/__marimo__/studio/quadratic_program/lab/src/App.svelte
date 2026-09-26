<script lang="ts">
  import Geometry from "./Geometry.svelte";
  import { observeMarimoValue } from "./lib/marimo-value.ts";
  import {
    type Bowl,
    nearestRow,
    type Region,
    type SweepRow,
    turn,
  } from "./lib/problem.ts";
  import Sensitivity from "./Sensitivity.svelte";

  let region = $state<Region>();
  let bowl = $state<Bowl>();
  let sweep = $state<SweepRow[]>();
  let direction = $state(0);
  let unavailable = $state(false);
  const fail = () => (unavailable = true);

  const row = $derived(sweep ? nearestRow(sweep, direction) : undefined);
  const held = $derived(
    row ? row.active.flatMap((active, wall) => (active ? [wall] : [])) : [],
  );

  // Typeset negative readings with a true minus sign, as the chart ticks do.
  const signed = (value: number, digits: number) =>
    value.toFixed(digits).replace(/^-/, "−");

  const onturn = (degrees: number) => {
    direction = turn(degrees);
  };

  // Follow the notebook's direction when it changes, and keep the reader's dial
  // when other values update.
  let notebookDirection: number | undefined;
  const followNotebook = (degrees: number) => {
    if (degrees !== notebookDirection) {
      notebookDirection = degrees;
      onturn(degrees);
    }
  };
</script>

<span
  id="region-data"
  hidden
  mo-value="region"
  use:observeMarimoValue={{
    onValue: (value: Region) => (region = value),
    onError: fail,
  }}
></span>
<span
  id="bowl-data"
  hidden
  mo-value="bowl"
  use:observeMarimoValue={{
    onValue: (value: Bowl) => (bowl = value),
    onError: fail,
  }}
></span>
<span
  id="sweep-data"
  hidden
  mo-value="sweep"
  use:observeMarimoValue={{
    onValue: (value: SweepRow[]) => (sweep = value),
    onError: fail,
  }}
></span>
<span
  id="direction-data"
  hidden
  mo-value="pull_direction.value"
  use:observeMarimoValue={{
    onValue: followNotebook,
    onError: fail,
  }}
></span>

<div class="lab">
  <header class="masthead">
    <p class="kicker">Quadratic programs</p>
    <h1>Sensitivity to the linear term</h1>
    <p class="lede">
      Turn the dial, or scrub the curve beneath it, to rotate the linear term
      <em>q</em>. Arrow keys step either one. The solution <em>x</em>* and the
      walls that hold it follow.
    </p>
  </header>

  <div class="instrument">
    <figure
      class="stage"
      aria-busy={!row && !unavailable}
      data-marimo-lens-inputs="region-data bowl-data sweep-data direction-data"
      data-marimo-lens-label="Feasible region, level curves, and the path of the optimum"
      data-marimo-lens-render-source={JSON.stringify({ path: "src/Geometry.svelte" })}
    >
      {#if unavailable}
        <p class="unavailable">The figure is unavailable.</p>
      {:else if region && bowl && sweep && row}
        <Geometry {region} {bowl} {sweep} {row} {direction} {onturn} />
      {/if}
    </figure>

    {#if sweep && row}
      <section
        class="chart"
        data-marimo-lens-inputs="sweep-data direction-data"
        data-marimo-lens-label="Optimal value and active walls by direction"
        data-marimo-lens-render-source={JSON.stringify({ path: "src/Sensitivity.svelte" })}
      >
        <h2>Optimal value by direction</h2>
        <Sensitivity {sweep} {row} {onturn} />
      </section>
    {/if}
  </div>

  <aside class="panel">
    {#if row}
      <dl
        class="readout"
        data-marimo-lens-inputs="sweep-data direction-data"
        data-marimo-lens-label="Solution for the current direction"
        data-marimo-lens-render-source={JSON.stringify({ path: "src/App.svelte" })}
      >
        <div>
          <dt>Direction of <em>q</em></dt>
          <dd>{row.direction}°</dd>
        </div>
        <div>
          <dt>Optimal value</dt>
          <dd>{signed(row.value, 3)}</dd>
        </div>
        <div>
          <dt><em>x</em>*</dt>
          <dd>({signed(row.optimum[0], 2)}, {signed(row.optimum[1], 2)})</dd>
        </div>
        <div>
          <dt>Active walls</dt>
          <dd class="held">
            {#each held as wall}
              <span><em>g</em><sub>{wall + 1}</sub> <span class="dual">λ {row.duals[wall].toFixed(2)}</span></span>
            {:else}
              <span>None</span>
            {/each}
          </dd>
        </div>
      </dl>
    {/if}

    <marimo-cell name="curvature"></marimo-cell>
  </aside>
</div>
