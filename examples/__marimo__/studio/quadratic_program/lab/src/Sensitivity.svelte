<script lang="ts">
  import { scaleLinear } from "d3-scale";
  import { line } from "d3-shape";

  import { arrowStep, heldRuns, type SweepRow } from "./lib/problem.ts";

  let {
    sweep,
    row,
    onturn,
  }: {
    sweep: SweepRow[];
    row: SweepRow;
    onturn: (degrees: number) => void;
  } = $props();

  const WIDTH = 520;
  const LEFT = 48;
  const RIGHT = 20;
  const TOP = 10;
  const CURVE = 150;
  const GAP = 26;
  const STRIP = 18;
  const AXIS = 24;

  const walls = $derived(row.active.length);
  const height = $derived(TOP + CURVE + GAP + walls * STRIP + AXIS);
  const x = scaleLinear().domain([0, 360]).range([LEFT, WIDTH - RIGHT]);
  const y = $derived(
    scaleLinear()
      .domain([
        Math.min(...sweep.map(({ value }) => value)),
        Math.max(...sweep.map(({ value }) => value)),
      ])
      .nice()
      .range([TOP + CURVE, TOP]),
  );
  const curve = $derived(
    line<SweepRow>()
      .x(({ direction }) => x(direction))
      .y(({ value }) => y(value))(sweep) ?? "",
  );
  const band = $derived(x(sweep[1].direction) - x(sweep[0].direction));
  const strip = (wall: number) => TOP + CURVE + GAP + (walls - 1 - wall) * STRIP;

  let svg: SVGSVGElement;
  let scrubbing = false;

  const directionAt = (event: PointerEvent) => {
    const matrix = svg.getScreenCTM()?.inverse();
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix);
    return Math.min(Math.max(x.invert(point.x), 0), 359);
  };

  const press = (event: PointerEvent) => {
    scrubbing = true;
    svg.setPointerCapture(event.pointerId);
    onturn(directionAt(event));
  };

  const scrub = (event: PointerEvent) => {
    if (scrubbing) {
      onturn(directionAt(event));
    }
  };

  const release = () => {
    scrubbing = false;
  };

  const step = (event: KeyboardEvent) => {
    const change = arrowStep(event.key, sweep);
    if (change !== undefined) {
      event.preventDefault();
      onturn(row.direction + change);
    }
  };
</script>

<svg
  bind:this={svg}
  class="sensitivity"
  viewBox="0 0 {WIDTH} {height}"
  role="slider"
  tabindex="0"
  aria-label="Direction of q on the optimal value chart"
  aria-valuemin="0"
  aria-valuemax="359"
  aria-valuenow={row.direction}
  aria-valuetext="{row.direction} degrees, optimal value {row.value.toFixed(3)}"
  onkeydown={step}
  onpointerdown={press}
  onpointermove={scrub}
  onpointerup={release}
  onpointercancel={release}
>
  {#each y.ticks(3) as tick}
    <line class="grid" x1={LEFT} x2={WIDTH - RIGHT} y1={y(tick)} y2={y(tick)} />
    <text class="tick" x={LEFT - 10} y={y(tick)}>{String(tick).replace("-", "−")}</text>
  {/each}
  <path class="curve" d={curve} />

  {#each { length: walls } as _, wall}
    <text class="tick wall-name" x={LEFT - 10} y={strip(wall) + STRIP / 2}>
      g<tspan class="subscript" dy="0.25em">{wall + 1}</tspan>
    </text>
    {#each heldRuns(sweep, wall) as [first, last]}
      <rect
        class="held"
        x={x(first) - band / 2}
        y={strip(wall) + 4}
        width={x(last) - x(first) + band}
        height={STRIP - 8}
      />
    {/each}
  {/each}

  <line class="cursor" x1={x(row.direction)} x2={x(row.direction)} y1={TOP} y2={height - AXIS} />
  <circle class="marker" cx={x(row.direction)} cy={y(row.value)} r="4.5" />

  {#each [0, 90, 180, 270, 360] as tick}
    <text class="tick axis" x={x(tick)} y={height - 6}>{tick}°</text>
  {/each}
</svg>
