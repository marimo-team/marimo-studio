import type { ValueReadResponse } from "@marimo-studio/protocol/value-read";

import { ownRecordValue } from "../records.ts";
import { applyValues, markValueError } from "./hosts.ts";

export const applyValueReadResponse = (
  selectors: readonly string[],
  response: ValueReadResponse,
  revision: string,
): void => {
  applyValues(response.values, revision);
  const responseError = ownRecordValue(response.errors, "*");
  selectors.forEach((selector) => {
    const hasValue = Object.hasOwn(response.values, selector);
    const error =
      ownRecordValue(response.errors, selector) ?? (hasValue ? undefined : responseError);
    if (error) {
      markValueError(selector, error, revision);
      return;
    }
    if (!hasValue) {
      markValueError(
        selector,
        {
          code: "missing-value-response",
          message: `The kernel response omitted ${JSON.stringify(selector)}.`,
        },
        revision,
      );
    }
  });
};
