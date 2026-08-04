import { z } from "zod";

const jsonCodec = <T extends z.core.$ZodType>(schema: T) =>
  z.codec(z.string(), schema, {
    decode: (source, context) => {
      try {
        return JSON.parse(source);
      } catch (error: unknown) {
        context.issues.push({
          code: "invalid_format",
          format: "json",
          input: source,
          message: error instanceof Error ? error.message : "Invalid JSON",
        });
        return z.NEVER;
      }
    },
    encode: (value) => JSON.stringify(value),
  });

export const surfaceSchema = z.enum(["notebook", "source", "preview"]);
export const axisSchema = z.enum(["x", "y"]);
export const studioModeSchema = z.enum(["notebook", "preview", "code", "workspace"]);

export type Surface = z.infer<typeof surfaceSchema>;
export type Axis = z.infer<typeof axisSchema>;
export type StudioMode = z.infer<typeof studioModeSchema>;

export interface PaneNode {
  type: "pane";
  id: string;
  surface: Surface;
}

export interface SplitNode {
  type: "split";
  id: string;
  axis: Axis;
  ratio: number;
  first: LayoutNode;
  second: LayoutNode;
}

export type LayoutNode = PaneNode | SplitNode;

const layoutNodeShapeSchema: z.ZodType<LayoutNode> = z.lazy(() =>
  z.discriminatedUnion("type", [
    z.object({
      type: z.literal("pane"),
      id: z.string(),
      surface: surfaceSchema,
    }),
    z.object({
      type: z.literal("split"),
      id: z.string().min(1),
      axis: axisSchema,
      ratio: z.number().min(0.1).max(0.9),
      first: layoutNodeShapeSchema,
      second: layoutNodeShapeSchema,
    }),
  ]),
);

const hasUniqueNodes = (root: LayoutNode): boolean => {
  const ids = new Set<string>();
  const surfaces = new Set<Surface>();
  const visit = (node: LayoutNode): boolean => {
    if (ids.has(node.id)) {
      return false;
    }
    ids.add(node.id);
    if (node.type === "pane") {
      if (node.id !== `pane-${node.surface}` || surfaces.has(node.surface)) {
        return false;
      }
      surfaces.add(node.surface);
      return true;
    }
    return visit(node.first) && visit(node.second);
  };
  return visit(root);
};

export const layoutNodeSchema = layoutNodeShapeSchema.refine(hasUniqueNodes, {
  message: "Layout panes and node identifiers must be unique.",
});

export const storedLayoutSchema = z.object({
  schema: z.literal(1),
  mode: studioModeSchema,
  code: layoutNodeSchema,
  workspace: layoutNodeSchema,
  compact: surfaceSchema.optional().catch(undefined),
});

const layoutCodec = jsonCodec(layoutNodeSchema);
export const storedLayoutCodec = jsonCodec(storedLayoutSchema);

export const decodeLayout = (source: string): LayoutNode | null => {
  const result = layoutCodec.safeDecode(source);
  return result.success ? result.data : null;
};
