import { parseErrorResponse } from "@marimo-studio/protocol/errors";

import { responseJsonOrNull } from "../json.ts";

export interface ResponseError {
  code: string;
  message: string;
  hint: string;
  transient: boolean;
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
  const detail = parseErrorResponse(await responseJsonOrNull(response.clone()));
  return {
    code: detail.error ?? "runtime-config-failed",
    message: detail.message ?? (await responseText(response, fallback)),
    hint: detail.hint ?? "",
    transient: detail.transient ?? false,
  };
};

export class RuntimeConfigRequestError extends Error {
  constructor(
    message: string,
    readonly code: string,
    readonly transient: boolean,
    readonly hint = "",
  ) {
    super(message);
    this.name = "RuntimeConfigRequestError";
  }
}
