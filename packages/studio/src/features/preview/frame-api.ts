import { z } from "zod";

const previewFrameSchema = z.object({
  marimoStudio: z.object({
    ready: z.function({ input: [], output: z.promise(z.void()) }),
    updateQuery: z.function({ input: [z.string()], output: z.promise(z.void()) }),
  }),
});

export const previewFrameApi = (frame: HTMLIFrameElement) => {
  const parsed = previewFrameSchema.safeParse(frame.contentWindow);
  return parsed.success ? parsed.data.marimoStudio : undefined;
};
