import { parseErrorResponse } from "@marimo-studio/protocol/errors";
import { jsonValueSchema } from "@marimo-studio/protocol/runtime-config";

export const errorMessage = (cause: unknown): string =>
  cause instanceof Error ? cause.message : String(cause);

/** Return a Studio error response's message followed by its next step. */
export const responseErrorMessage = async (
  response: Response,
  fallback: string,
): Promise<string> => {
  try {
    const error = parseErrorResponse(jsonValueSchema.parse(await response.json()));
    const message = error.message ?? fallback;
    return error.hint ? `${message} ${error.hint}` : message;
  } catch {
    return fallback;
  }
};
