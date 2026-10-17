import { z } from "zod";

import { isRenderSource, renderSourceSchema, sourceLocationSchema } from "./projections.ts";
import { ownRecordSchema } from "./records.ts";
import { jsonValueSchema } from "./runtime-config.ts";
import { projectDiagnosticSchema } from "./view-project.ts";

/** A notebook output or a cell's output as marimo shows it. */
export const renderedMediaSchema = z
  .object({
    mimetype: z.string().min(1),
    data: jsonValueSchema,
  })
  .strict();

/**
 * The body a page posts to its view's `render` support route. The Server
 * runtime names the render, and Studio reads its inputs from the kernel.
 * Browser runtimes in edit mode also post the render's reads: values by value
 * target, outputs by output target, and cells by cell target.
 */
export const renderRequestSchema = z.union([
  z
    .object({
      revision: z.string(),
      render: renderSourceSchema,
    })
    .strict(),
  z
    .object({
      revision: z.string(),
      render: renderSourceSchema,
      values: ownRecordSchema(z.string(), jsonValueSchema),
      outputs: ownRecordSchema(z.string(), renderedMediaSchema),
      cells: ownRecordSchema(z.string(), renderedMediaSchema),
    })
    .strict(),
]);

const bundleIdSchema = z.string().regex(/^[a-f0-9]{64}$/);
// A normalized relative POSIX path inside one bundle.
const bundlePathSchema = z
  .string()
  .refine(isRenderSource, { message: "Bundle paths are normalized relative paths" });

export const bundleFileSchema = z
  .object({
    path: bundlePathSchema,
    mediaType: z.string().min(1),
    sha256: z.string().regex(/^[a-f0-9]{64}$/),
    size: z.int().nonnegative(),
  })
  .strict();

const fractionSchema = z.number().min(0).max(1);

/**
 * A rectangle on one surface of a rendered file and the notebook results it
 * shows. `rect` is in fractions of the surface's width and height from its top
 * left: `page` of a PDF, counted from 1, an image, or a video's frames from
 * `start` until `end` seconds. Each read names a target the render reads,
 * optionally narrowed by selector steps such as `joint[2][3]`. `source` is
 * where the render's source places the part.
 */
export const renderRegionSchema = z
  .object({
    file: bundlePathSchema,
    rect: z
      .object({
        x: fractionSchema,
        y: fractionSchema,
        width: fractionSchema.positive(),
        height: fractionSchema.positive(),
      })
      .strict()
      .refine(({ x, y, width, height }) => x + width <= 1 + 1e-6 && y + height <= 1 + 1e-6, {
        message: "A region's rectangle fits its surface",
      }),
    reads: z.array(z.string().min(1).max(4_096)).max(64),
    page: z.int().positive().nullable(),
    start: z.number().nonnegative().nullable(),
    end: z.number().positive().nullable(),
    source: sourceLocationSchema.nullable(),
    label: z.string().min(1).max(256).nullable(),
  })
  .strict()
  .refine(({ start, end }) => start === null || end === null || end > start, {
    message: "A region ends after it starts",
  });

const bundleContent = {
  files: z.array(bundleFileSchema).nonempty(),
  main: bundlePathSchema,
  preview: bundlePathSchema.nullable(),
  regions: z.array(renderRegionSchema).max(4_096),
};

const checkContent = (
  content: {
    readonly files: readonly BundleFile[];
    readonly main: string;
    readonly preview: string | null;
    readonly regions: readonly RenderRegion[];
  },
  context: z.RefinementCtx,
) => {
  const paths = new Set(content.files.map((file) => file.path));
  if (paths.size !== content.files.length) {
    context.addIssue({ code: "custom", path: ["files"], message: "A bundle lists each file once" });
  }
  if (!paths.has(content.main)) {
    context.addIssue({ code: "custom", path: ["main"], message: "main names a bundle file" });
  }
  if (content.preview === content.main) {
    context.addIssue({
      code: "custom",
      path: ["preview"],
      message: "preview names a file other than main",
    });
  }
  if (content.preview !== null && !paths.has(content.preview)) {
    context.addIssue({ code: "custom", path: ["preview"], message: "preview names a bundle file" });
  }
  content.regions.forEach((region, index) => {
    if (!paths.has(region.file)) {
      context.addIssue({
        code: "custom",
        path: ["regions", index, "file"],
        message: "A region names a bundle file",
      });
    }
  });
};

/**
 * One render's bundle for the inputs it read. `main` and `preview` name files
 * in `files`, `absent` lists the targets read without a current result, and
 * `regions` locates the parts of the files that notebook results produced.
 */
export const renderBundleSchema = z
  .object({
    render: renderSourceSchema,
    bundle: bundleIdSchema,
    ...bundleContent,
    warnings: z.array(projectDiagnosticSchema),
    absent: z.array(z.string()),
  })
  .strict()
  .superRefine(checkContent);

/**
 * `renders/index.json` in a static export. `bundles` holds each bundle's
 * files and regions once, by bundle ID. `states` maps each prepared state's
 * fingerprint, then each render source, to the bundle the render published
 * for that state with the warnings and absent reads of that state.
 */
export const renderIndexSchema = z
  .object({
    schema: z.literal(2),
    bundles: ownRecordSchema(
      bundleIdSchema,
      z.object(bundleContent).strict().superRefine(checkContent),
    ),
    states: ownRecordSchema(
      z.string(),
      ownRecordSchema(
        renderSourceSchema,
        z
          .object({
            bundle: bundleIdSchema,
            warnings: z.array(projectDiagnosticSchema),
            absent: z.array(z.string()),
          })
          .strict(),
      ),
    ),
  })
  .strict()
  .superRefine((index, context) => {
    for (const [state, renders] of Object.entries(index.states)) {
      for (const [render, { bundle }] of Object.entries(renders)) {
        if (index.bundles[bundle] === undefined) {
          context.addIssue({
            code: "custom",
            path: ["states", state, render, "bundle"],
            message: "A state names a bundle the index lists",
          });
        }
      }
    }
  });

/** Return the bundle `render` published for `state` in a static export's index. */
export const indexedBundle = (
  index: RenderIndex,
  state: string,
  render: string,
): RenderBundle | undefined => {
  const entry = index.states[state]?.[render];
  const content = entry && index.bundles[entry.bundle];
  return entry && content ? { render, ...entry, ...content } : undefined;
};

export type RenderedMedia = z.infer<typeof renderedMediaSchema>;
export type RenderRequest = z.infer<typeof renderRequestSchema>;
export type BundleFile = z.infer<typeof bundleFileSchema>;
export type RenderBundle = z.infer<typeof renderBundleSchema>;
export type RenderRegion = z.infer<typeof renderRegionSchema>;
export type RenderIndex = z.infer<typeof renderIndexSchema>;
