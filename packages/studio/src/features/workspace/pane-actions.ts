import type { Placement, Surface } from "./model.ts";

import { surfaceSchema } from "./schema.ts";

export const SURFACES: readonly Surface[] = surfaceSchema.options;

export const SURFACE_LABELS = {
  notebook: "Notebook",
  source: "HTML & CSS",
  preview: "Preview",
} satisfies Record<Surface, string>;

export const PLACEMENTS: readonly {
  value: Placement;
  label: string;
  relation: string;
}[] = [
  { value: "left", label: "Left", relation: "to the left of" },
  { value: "right", label: "Right", relation: "to the right of" },
  { value: "above", label: "Above", relation: "above" },
  { value: "below", label: "Below", relation: "below" },
];
