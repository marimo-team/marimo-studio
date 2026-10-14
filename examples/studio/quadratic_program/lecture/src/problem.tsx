export type Point = [number, number];

/** The feasible region `Gx <= h` and its walls, from the notebook's `region`. */
export interface Region {
  corners: Point[];
  walls: [Point, Point][];
}

/** The principal axes of `P` and its level-set radii, from `bowl`. */
export interface Bowl {
  angle: number;
  levels: [number, number][];
}

/** One solve of the program, from `solution`. */
export interface Solution {
  value: number;
  optimum: Point;
  center: Point;
  contact: [number, number];
  duals: number[];
  active: boolean[];
}

const EXTENT = 3;

const Ellipse = (
  { center, radii, angle, className }: {
    center: Point;
    radii: [number, number];
    angle: number;
    className: string;
  },
) => (
  <ellipse
    className={className}
    cx={center[0]}
    cy={center[1]}
    rx={radii[0]}
    ry={radii[1]}
    transform={`rotate(${angle} ${center[0]} ${center[1]})`}
  />
);

/** Offset the optimum's label away from the bottom of the bowl, clear of the contact curve. */
const labelOffset = ({ optimum, center }: Solution): Point => {
  const away: Point = [optimum[0] - center[0], optimum[1] - center[1]];
  const distance = Math.hypot(...away);
  return distance > 1e-3
    ? [(0.3 * away[0]) / distance, (0.3 * away[1]) / distance]
    : [0.2, 0.2];
};

/**
 * Draw the region, the walls, the level curves, and the solution in problem
 * coordinates. With `steps`, each layer is a Reveal fragment in reading order.
 */
export const ProblemFigure = (
  { region, bowl, solution, steps = false }: {
    region: Region;
    bowl: Bowl;
    solution: Solution;
    steps?: boolean;
  },
) => {
  const layer = (name: string, index: number) => ({
    className: steps ? `${name} fragment` : name,
    "data-fragment-index": steps ? index : undefined,
  });
  const [x, y] = solution.optimum;
  const [dx, dy] = labelOffset(solution);
  return (
    <svg
      className="problem-figure"
      viewBox={`${-EXTENT} ${-EXTENT} ${2 * EXTENT} ${2 * EXTENT}`}
      role="img"
      aria-label="Feasible region, level curves, and the solution"
    >
      <g transform="scale(1 -1)">
        <polygon
          {...layer("region", 1)}
          points={region.corners.map((corner) => corner.join(",")).join(" ")}
        />
        <g {...layer("walls", 0)}>
          {region.walls.map(([start, end], index) => (
            <line
              key={index}
              className={solution.active[index] ? "wall active" : "wall"}
              x1={start[0]}
              y1={start[1]}
              x2={end[0]}
              y2={end[1]}
            />
          ))}
        </g>
        <g {...layer("levels", 2)}>
          {bowl.levels.map((radii, index) => (
            <Ellipse
              key={index}
              className="level"
              center={solution.center}
              radii={radii}
              angle={bowl.angle}
            />
          ))}
        </g>
        <g {...layer("answer", 3)}>
          <Ellipse
            className="contact"
            center={solution.center}
            radii={solution.contact}
            angle={bowl.angle}
          />
          <circle
            className="center"
            cx={solution.center[0]}
            cy={solution.center[1]}
            r={0.07}
          />
          <circle className="optimum" cx={x} cy={y} r={0.08} />
        </g>
      </g>
      <text
        {...layer("label", 3)}
        x={x + dx}
        y={-(y + dy)}
        textAnchor="middle"
        dominantBaseline="central"
      >
        x*
      </text>
    </svg>
  );
};
