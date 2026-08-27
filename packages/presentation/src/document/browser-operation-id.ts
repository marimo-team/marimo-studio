let sequence = 0;

export const nextBrowserOperationId = (): string => {
  const entropy = globalThis.crypto.getRandomValues(new Uint32Array(4));
  sequence = sequence >= Number.MAX_SAFE_INTEGER ? 1 : sequence + 1;
  return `${Array.from(entropy, (value) => value.toString(36).padStart(7, "0")).join("-")}-${sequence.toString(36)}`;
};
