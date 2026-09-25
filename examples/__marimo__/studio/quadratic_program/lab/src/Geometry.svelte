<script lang="ts">
  import type { Bowl, Region, SweepRow } from "./lib/problem.ts";

  let {
    region,
    bowl,
    sweep,
    row,
    direction,
    onturn,
  }: {
    region: Region;
    bowl: Bowl;
    sweep: SweepRow[];
    row: SweepRow;
    direction: number;
    onturn: (degrees: number) => void;
  } = $props();

  const WINDOW = 3;
  const DIAL = 3.35;
  const EXTENT = DIAL + 0.35;

  const radians = $derived((direction * Math.PI) / 180);
  const handle = $derived([DIAL * Math.cos(radians), DIAL * Math.sin(radians)]);
  const trail = $derived(sweep.map(({ optimum }) => optimum.join(",")).join(" "));
  const corners = $derived(region.corners.map((corner) => corner.join(",")).join(" "));

  let svg: SVGSVGElement;
  let dragging = false;

  const angleAt = (event: PointerEvent) => {
    const matrix = svg.getScreenCTM()?.inverse();
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix);
    return (Math.atan2(-point.y, point.x) * 180) / Math.PI;
  };

  const press = (event: PointerEvent) => {
    dragging = true;
    svg.setPointerCapture(event.pointerId);
    onturn(angleAt(event));
  };

  const drag = (event: PointerEvent) => {
    if (dragging) {
      onturn(angleAt(event));
    }
  };

  const release = () => {
    dragging = false;
  };

  const steps: Record<string, number> = {
    ArrowUp: 2,
    ArrowRight: 2,
    ArrowDown: -2,
    ArrowLeft: -2,
  };

  const step = (event: KeyboardEvent) => {
    if (event.key in steps) {
      event.preventDefault();
      onturn(direction + steps[event.key]);
    }
  };
</script>

<svg
  bind:this={svg}
  class="geometry"
  viewBox="{-EXTENT} {-EXTENT} {2 * EXTENT} {2 * EXTENT}"
  role="slider"
  tabindex="0"
  aria-label="Direction of q"
  aria-valuemin="0"
  aria-valuemax="359"
  aria-valuenow={Math.round(direction) % 360}
  aria-valuetext="{Math.round(direction) % 360} degrees"
  onpointerdown={press}
  onpointermove={drag}
  onpointerup={release}
  onpointercancel={release}
  onkeydown={step}
>
  <defs>
    <clipPath id="lab-window">
      <circle r={WINDOW} />
    </clipPath>
  </defs>
  <circle class="window" r={WINDOW} />
  <g transform="scale(1 -1)">
    <g clip-path="url(#lab-window)">
      <polygon class="region" points={corners} />
      {#each region.walls as [start, end], index}
        <line
          class="wall"
          class:active={row.active[index]}
          x1={start[0]}
          y1={start[1]}
          x2={end[0]}
          y2={end[1]}
        />
      {/each}
      {#each bowl.levels as radii}
        <ellipse
          class="level"
          cx={row.center[0]}
          cy={row.center[1]}
          rx={radii[0]}
          ry={radii[1]}
          transform="rotate({bowl.angle} {row.center[0]} {row.center[1]})"
        />
      {/each}
      <polyline class="trail" points={trail} />
      {#if row.contact[0] > 0}
        <ellipse
          class="contact"
          cx={row.center[0]}
          cy={row.center[1]}
          rx={row.contact[0]}
          ry={row.contact[1]}
          transform="rotate({bowl.angle} {row.center[0]} {row.center[1]})"
        />
      {/if}
      <circle class="center" cx={row.center[0]} cy={row.center[1]} r="0.07" />
      <circle class="optimum" cx={row.optimum[0]} cy={row.optimum[1]} r="0.09" />
    </g>
    <circle class="dial" r={DIAL} />
    <line class="pull" x1="0" y1="0" x2={handle[0]} y2={handle[1]} />
    <circle class="handle" cx={handle[0]} cy={handle[1]} r="0.15" />
  </g>
  <text class="handle-label" x={handle[0] * 1.08} y={-handle[1] * 1.08}>q</text>
</svg>
