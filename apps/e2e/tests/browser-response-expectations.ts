import { errorResponseSchema } from "@marimo-studio/protocol/errors";

export interface BrowserResponseExpectation {
  status: number;
  path: RegExp;
  error?: string;
  count?: number;
  required?: boolean;
}

export interface BrowserResponseIdentity {
  status(): number;
  text(): Promise<string>;
  url(): string;
}

interface TrackedBrowserResponse extends BrowserResponseExpectation {
  seen: number;
  pending: number;
  isRecovered: boolean;
}

const expectedCardinality = (count: number | undefined): number => {
  const cardinality = count ?? 1;
  if (!Number.isSafeInteger(cardinality) || cardinality < 1) {
    throw new RangeError("Browser response expectations require a positive count.");
  }
  return cardinality;
};

const responseText = async (response: BrowserResponseIdentity): Promise<string> => {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const unavailable = new Promise<string>((resolveUnavailable) => {
    timer = setTimeout(() => resolveUnavailable("<response body unavailable>"), 2_000);
  });
  try {
    return await Promise.race([
      response.text().catch(() => "<unreadable response body>"),
      unavailable,
    ]);
  } finally {
    if (timer !== undefined) {
      clearTimeout(timer);
    }
  }
};

export class BrowserResponseExpectations {
  private readonly items: TrackedBrowserResponse[] = [];

  expect(expectation: BrowserResponseExpectation): () => void {
    expectedCardinality(expectation.count);
    const tracked: TrackedBrowserResponse = {
      ...expectation,
      seen: 0,
      pending: 0,
      isRecovered: false,
    };
    this.items.push(tracked);
    return () => {
      tracked.isRecovered = true;
    };
  }

  async inspect(response: BrowserResponseIdentity): Promise<string | undefined> {
    if (response.status() < 400) {
      return undefined;
    }
    const url = new URL(response.url());
    const eligible = this.items.filter((item) => {
      item.path.lastIndex = 0;
      return (
        !item.isRecovered &&
        item.seen < expectedCardinality(item.count) &&
        item.status === response.status() &&
        item.path.test(url.pathname)
      );
    });
    const statusAllowance = eligible.find((item) => item.error === undefined);
    if (statusAllowance !== undefined) {
      statusAllowance.seen += 1;
      return undefined;
    }

    const reserved = eligible.filter((item) => item.error !== undefined);
    reserved.forEach((item) => {
      item.pending += 1;
    });
    const body = await responseText(response);
    reserved.forEach((item) => {
      item.pending -= 1;
    });

    let error: string | undefined;
    try {
      const payload = errorResponseSchema.safeParse(JSON.parse(body));
      if (payload.success) {
        error = payload.data.error;
      }
    } catch {
      // The bounded body remains in the diagnostic for non-JSON responses.
    }
    const allowance = reserved.find(
      (item) => item.error === error && item.seen < expectedCardinality(item.count),
    );
    if (allowance !== undefined) {
      allowance.seen += 1;
      return undefined;
    }
    const detail = body.replace(/\s+/g, " ").slice(0, 500);
    return `http ${response.status()}${error ? ` ${error}` : ""}: ${response.url()} (${detail})`;
  }

  diagnostics(): string[] {
    const messages: string[] = [];
    for (const response of this.items) {
      const cardinality = expectedCardinality(response.count);
      if (response.pending > 0) {
        messages.push(
          `expected http ${response.status} ${response.path} retained ${response.pending} pending response(s)`,
        );
      }
      if (response.required !== false && response.seen !== cardinality) {
        messages.push(
          `expected http ${response.status} ${response.path} exactly ${cardinality} time(s), saw ${response.seen}`,
        );
      }
      if (response.seen > 0 && !response.isRecovered) {
        messages.push(`expected http ${response.status} ${response.path} had no observed recovery`);
      }
    }
    return messages;
  }
}
