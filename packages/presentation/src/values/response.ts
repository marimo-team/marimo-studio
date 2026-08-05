import type { ValueReadResponse } from "@marimo-studio/protocol/value-read";

import { applyValues, markValueError } from "./hosts.ts";

export const applyValueReadResponse = (
  selectors: readonly string[],
  response: ValueReadResponse,
): void => {
  applyValues(response.values);
  const responseError = response.errors["*"];
  selectors.forEach((selector) => {
    const hasValue = Object.hasOwn(response.values, selector);
    const error = response.errors[selector] ?? (hasValue ? undefined : responseError);
    if (error) {
      markValueError(selector, error);
      return;
    }
    if (!hasValue) {
      markValueError(selector, {
        code: "missing-value-response",
        message: `The kernel response omitted ${JSON.stringify(selector)}.`,
      });
    }
  });
};
