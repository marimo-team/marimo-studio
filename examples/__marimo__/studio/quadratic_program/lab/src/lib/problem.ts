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

/** One solve of the program, as recorded in the notebook's `sweep`. */
export interface SweepRow {
  direction: number;
  value: number;
  optimum: Point;
  center: Point;
  contact: [number, number];
  duals: number[];
  active: boolean[];
}

/** Wrap an angle in degrees into [0, 360). */
export const turn = (degrees: number) => ((degrees % 360) + 360) % 360;

const separation = (a: number, b: number) => {
  const difference = Math.abs(turn(a) - turn(b));
  return Math.min(difference, 360 - difference);
};

/** Return the direction change an arrow key asks for, one solved direction at a time. */
export const arrowStep = (key: string, sweep: SweepRow[]): number | undefined => {
  const spacing = sweep[1].direction - sweep[0].direction;
  const steps: Record<string, number> = {
    ArrowUp: spacing,
    ArrowRight: spacing,
    ArrowDown: -spacing,
    ArrowLeft: -spacing,
  };
  return steps[key];
};

/** Return the solved row whose direction of q is closest to `degrees`. */
export const nearestRow = (sweep: SweepRow[], degrees: number) =>
  sweep.reduce((best, row) =>
    separation(row.direction, degrees) < separation(best.direction, degrees)
      ? row
      : best
  );

/** Return the first and last direction of each run of solves held by `wall`. */
export const heldRuns = (sweep: SweepRow[], wall: number) => {
  const runs: [number, number][] = [];
  sweep.forEach((row, index) => {
    if (!row.active[wall]) {
      return;
    }
    const run = runs.at(-1);
    if (run && sweep[index - 1]?.active[wall]) {
      run[1] = row.direction;
    } else {
      runs.push([row.direction, row.direction]);
    }
  });
  return runs;
};
