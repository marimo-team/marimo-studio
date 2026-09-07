import type { PresentationRefreshBarrierMessage } from "@marimo-studio/protocol/preview-messages";

import { parseEditorDocumentMutationAcknowledgement } from "@marimo-studio/protocol/development-events";

interface MutationBarrierOptions {
  readonly runtime: string;
  readonly view: string;
  readonly frame: HTMLIFrameElement;
  active(): boolean;
  lifecycleId(): number;
  receiver(): "absent" | "other" | "ready";
}

interface PendingMutationBarrier {
  readonly fail: (cause: unknown) => void;
  readonly start: () => void;
  readonly timeout: ReturnType<typeof setTimeout>;
  started: boolean;
}

const MUTATION_BARRIER_TIMEOUT_MS = 4_000;

export class PreviewMutationBarriers {
  private readonly pending = new Set<PendingMutationBarrier>();

  constructor(private readonly options: MutationBarrierOptions) {}

  pause(generation: number): Promise<void> {
    const { frame, runtime, view } = this.options;
    const target = frame.contentWindow;
    const lifecycleId = this.options.lifecycleId();
    if (
      !this.options.active() ||
      target === null ||
      frame.src === "about:blank" ||
      this.options.receiver() === "other"
    ) {
      return Promise.reject(
        new DOMException("The presentation is not ready to pause.", "InvalidStateError"),
      );
    }
    const channel = new MessageChannel();
    return new Promise<void>((resolve, reject) => {
      let owner!: PendingMutationBarrier;
      const settle = (complete: () => void) => {
        clearTimeout(owner.timeout);
        channel.port1.onmessage = null;
        channel.port1.onmessageerror = null;
        channel.port1.close();
        if (!owner.started) {
          channel.port2.close();
        }
        this.pending.delete(owner);
        complete();
      };
      const fail = (cause: unknown) => {
        if (owner.started) {
          try {
            channel.port1.postMessage({
              schema: 1,
              type: "marimo-studio:presentation-refresh-barrier-failed",
              generation,
            });
          } catch {
            // Closing the local port below still retires this barrier owner.
          }
        }
        settle(() => reject(cause));
      };
      const start = () => {
        if (owner.started) {
          return;
        }
        if (
          !this.options.active() ||
          lifecycleId !== this.options.lifecycleId() ||
          target !== frame.contentWindow ||
          frame.src === "about:blank"
        ) {
          fail(new DOMException("The presentation document changed.", "AbortError"));
          return;
        }
        if (this.options.receiver() !== "ready") {
          return;
        }
        owner.started = true;
        const message: PresentationRefreshBarrierMessage = {
          type: "marimo-studio:presentation-refresh-barrier",
          runtime,
          lifecycleId,
          view,
          generation,
        };
        try {
          target.postMessage(message, "*", [channel.port2]);
        } catch (cause) {
          channel.port2.close();
          fail(cause);
        }
      };
      owner = {
        fail,
        start,
        started: false,
        timeout: setTimeout(
          () => fail(new DOMException("The presentation did not pause in time.", "TimeoutError")),
          MUTATION_BARRIER_TIMEOUT_MS,
        ),
      };
      channel.port1.onmessage = (event) => {
        const acknowledgement = parseEditorDocumentMutationAcknowledgement(event.data);
        if (
          acknowledgement &&
          acknowledgement.type === "marimo-studio:editor-document-mutation-ready" &&
          acknowledgement.generation === generation
        ) {
          try {
            channel.port1.postMessage({
              schema: 1,
              type: "marimo-studio:presentation-refresh-barrier-accepted",
              generation,
            });
            settle(resolve);
          } catch (cause) {
            fail(cause);
          }
        } else {
          fail(new DOMException("The presentation returned an invalid barrier.", "DataError"));
        }
      };
      channel.port1.onmessageerror = () =>
        fail(new DOMException("The presentation rejected the mutation barrier.", "DataError"));
      channel.port1.start();
      this.pending.add(owner);
      owner.start();
    });
  }

  receiverReady(): void {
    for (const barrier of this.pending) {
      barrier.start();
    }
  }

  retire(cause: unknown, startedOnly = false): void {
    for (const barrier of this.pending) {
      if (!startedOnly || barrier.started) {
        barrier.fail(cause);
      }
    }
  }
}
