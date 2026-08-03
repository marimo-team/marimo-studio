interface RetryOptions<T> {
  operation: () => Promise<T>;
  delays: readonly number[];
  retryWhen: (error: unknown) => boolean;
  signal?: AbortSignal;
}

const wait = (delay: number, signal?: AbortSignal): Promise<void> =>
  new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("The request was aborted", "AbortError"));
      return;
    }
    const aborted = () => {
      clearTimeout(timeout);
      reject(new DOMException("The request was aborted", "AbortError"));
    };
    const timeout = setTimeout(() => {
      signal?.removeEventListener("abort", aborted);
      resolve();
    }, delay);
    signal?.addEventListener("abort", aborted, { once: true });
  });

export const retry = async <T>({
  operation,
  delays,
  retryWhen,
  signal,
}: RetryOptions<T>): Promise<T> => {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await operation();
    } catch (error) {
      const delay = delays[attempt];
      if (delay === undefined || !retryWhen(error)) {
        throw error;
      }
      await wait(delay, signal);
    }
  }
};
