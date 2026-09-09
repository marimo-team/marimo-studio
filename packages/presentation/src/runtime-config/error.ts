import type { JsonValue } from "@marimo-studio/protocol/runtime-config";

import { parseErrorResponse } from "@marimo-studio/protocol/errors";

import { responseJsonOrNull } from "../json.ts";

export interface ResponseError {
  code: string;
  message: string;
  hint: string;
  transient: boolean;
  details: Record<string, JsonValue>;
}

const responseText = async (response: Response, fallback: string) => {
  if (response.headers.get("content-type")?.includes("text/html")) {
    return fallback;
  }
  return (await response.text()).trim() || fallback;
};

export const readResponseError = async (
  response: Response,
  fallback: string,
): Promise<ResponseError> => {
  const { error, message, hint, transient, ...details } = parseErrorResponse(
    await responseJsonOrNull(response.clone()),
  );
  return {
    code: error ?? "runtime-config-failed",
    message: message ?? (await responseText(response, fallback)),
    hint: hint ?? "",
    transient: transient ?? false,
    details,
  };
};

export class RuntimeConfigRequestError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly transient: boolean,
    readonly hint = "",
    readonly details: Record<string, JsonValue> = {},
  ) {
    super(message);
    this.name = "RuntimeConfigRequestError";
  }
}
