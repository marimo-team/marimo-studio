import type { ProjectionKind } from "./static-values.ts";

type ProjectionCopy = {
  readonly message: string;
  readonly hint: string;
};

const PROJECTION_USAGE_HINT =
  'Use <marimo-cell name="..."> for a complete cell display, ' +
  '<marimo-output value="..."> for one Python object, or mo-value="..." ' +
  "when browser code needs JSON-compatible data.";

const projection = {
  cell: { subject: "<marimo-cell>", attribute: "name" },
  output: { subject: "<marimo-output>", attribute: "value" },
  value: { subject: "mo-value", attribute: "selector" },
} satisfies Record<
  ProjectionKind,
  { readonly subject: string; readonly attribute: string }
>;

export const projectionUsageHint = (): string => PROJECTION_USAGE_HINT;

export const projectionAttributeMissing = (
  kind: ProjectionKind,
): ProjectionCopy => {
  const { subject, attribute } = projection[kind];
  return {
    message: `${subject} requires a non-empty ${attribute}.`,
    hint: PROJECTION_USAGE_HINT,
  };
};

export const projectionAttributeDuplicate = (
  kind: ProjectionKind,
): ProjectionCopy => {
  const { subject, attribute } = projection[kind];
  return {
    message: `${subject} declares ${attribute} more than once.`,
    hint: `Keep one ${attribute} on this projection. ${PROJECTION_USAGE_HINT}`,
  };
};

export const projectionTargetUnbounded = (
  kind: ProjectionKind,
): ProjectionCopy => {
  const { subject, attribute } = projection[kind];
  return {
    message: `Studio cannot determine every possible ${subject} ${attribute}.`,
    hint:
      `Use a literal or const-backed ${attribute}. Add data-marimo-allow="*" when runtime selection is intentional.`,
  };
};

export const projectionWildcardInvalid = (): ProjectionCopy => ({
  message: 'data-marimo-allow must be the literal "*".',
  hint:
    "Use this attribute when a projection selector is selected dynamically at runtime.",
});

export const projectionKindConflict = (
  tag: "marimo-cell" | "marimo-output",
): ProjectionCopy => ({
  message: `<${tag}> cannot also declare mo-value.`,
  hint: PROJECTION_USAGE_HINT,
});
