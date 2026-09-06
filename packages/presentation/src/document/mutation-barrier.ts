import type { PresentationRefreshBarrierResult } from "@marimo-studio/protocol/development-events";

export interface PresentationMutationBarrierPort {
  close(): void;
  postMessage(message: {
    schema: 1;
    type: "marimo-studio:editor-document-mutation-ready";
    generation: number;
  }): void;
}

export const coordinatePresentationMutationBarrier = async ({
  drained,
  generation,
  onFailure,
  port,
  result,
  signal,
}: {
  drained: Promise<unknown>;
  generation: number;
  onFailure: () => void;
  port: PresentationMutationBarrierPort;
  result: Promise<PresentationRefreshBarrierResult>;
  signal: AbortSignal;
}): Promise<void> => {
  let cancel = () => {};
  const cancellation = new Promise<void>((resolve) => {
    cancel = resolve;
  });
  const abort = () => cancel();
  signal.addEventListener("abort", abort, { once: true });
  try {
    await Promise.race([drained, cancellation]);
    if (signal.aborted) {
      throw signal.reason;
    }
    port.postMessage({
      schema: 1,
      type: "marimo-studio:editor-document-mutation-ready",
      generation,
    });
    const outcome = await result;
    if (outcome.type === "marimo-studio:presentation-refresh-barrier-failed") {
      onFailure();
    }
  } catch {
    onFailure();
    port.close();
  } finally {
    signal.removeEventListener("abort", abort);
  }
};
