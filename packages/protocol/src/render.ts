import { z } from "zod";

import { isRenderSource, renderSourceSchema } from "./projections.ts";
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

/**
 * One render's bundle for the inputs it read. `main` and `preview` name files
 * in `files`, and `absent` lists the targets read without a current result.
 */
export const renderBundleSchema = z
  .object({
    render: renderSourceSchema,
    bundle: bundleIdSchema,
    files: z.array(bundleFileSchema).nonempty(),
    main: bundlePathSchema,
    preview: bundlePathSchema.nullable(),
    warnings: z.array(projectDiagnosticSchema),
    absent: z.array(z.string()),
  })
  .strict()
  .superRefine((result, context) => {
    const paths = new Set(result.files.map((file) => file.path));
    if (paths.size !== result.files.length) {
      context.addIssue({
        code: "custom",
        path: ["files"],
        message: "A bundle lists each file once",
      });
    }
    if (!paths.has(result.main)) {
      context.addIssue({ code: "custom", path: ["main"], message: "main names a bundle file" });
    }
    if (result.preview === result.main) {
      context.addIssue({
        code: "custom",
        path: ["preview"],
        message: "preview names a file other than main",
      });
    }
    if (result.preview !== null && !paths.has(result.preview)) {
      context.addIssue({
        code: "custom",
        path: ["preview"],
        message: "preview names a bundle file",
      });
    }
  });

/**
 * `renders/index.json` in a static export: the bundle of each render for
 * each prepared state, keyed by state fingerprint, then by render source.
 */
export const renderIndexSchema = z
  .object({
    schema: z.literal(1),
    states: ownRecordSchema(z.string(), ownRecordSchema(renderSourceSchema, renderBundleSchema)),
  })
  .strict();

export type RenderedMedia = z.infer<typeof renderedMediaSchema>;
export type RenderRequest = z.infer<typeof renderRequestSchema>;
export type BundleFile = z.infer<typeof bundleFileSchema>;
export type RenderBundle = z.infer<typeof renderBundleSchema>;
export type RenderIndex = z.infer<typeof renderIndexSchema>;
