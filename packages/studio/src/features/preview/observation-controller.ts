import type { RuntimeStatusReport } from "@marimo-studio/protocol/browser-observations";
import type { ObserveViewRequest } from "@marimo-studio/protocol/development-events";
import type {
  ObserveViewMessage,
  ViewObservationMessage,
} from "@marimo-studio/protocol/preview-messages";

import type { RecordBrowserObservation } from "./observation-remote.ts";

interface PendingObservation {
  message: ObserveViewMessage;
  terminalUpload: boolean;
}

type AcceptObservation = (message: ViewObservationMessage) => RuntimeStatusReport;

export class PreviewObservationController {
  private readonly requests = new Map<string, PendingObservation>();

  constructor(
    private readonly runtime: string,
    private readonly preview: HTMLIFrameElement,
    private readonly accept: AcceptObservation,
    private readonly record?: RecordBrowserObservation,
  ) {}

  request(request: ObserveViewRequest): void {
    if (request.runtime !== this.runtime) {
      return;
    }
    this.requests.clear();
    this.requests.set(request.requestId, {
      message: {
        type: "marimo-studio:observe-view",
        runtime: request.runtime,
        view: request.view,
        revision: request.revision,
        runtimeInstance: request.runtimeInstance,
        requestId: request.requestId,
      },
      terminalUpload: false,
    });
    this.post();
  }

  post(): void {
    for (const request of this.requests.values()) {
      if (!request.terminalUpload) {
        this.preview.contentWindow?.postMessage(request.message, globalThis.location.origin);
      }
    }
  }

  receive(message: ViewObservationMessage): void {
    const request = this.requests.get(message.requestId);
    const expected = request?.message;
    if (
      request === undefined ||
      expected === undefined ||
      request.terminalUpload ||
      expected.view !== message.view ||
      expected.runtime !== message.runtime ||
      expected.revision !== message.revision ||
      expected.runtimeInstance !== message.runtimeInstance
    ) {
      return;
    }
    const runtimeStatus = this.accept(message);
    const observation = {
      view: message.view,
      runtime: message.runtime,
      revision: message.revision,
      state: message.state,
      diagnostics: message.diagnostics,
      runtimeInstance: message.runtimeInstance,
      sessionId: message.sessionId,
      requestId: message.requestId,
      query: message.query,
      runtimeStatus,
    };
    if (message.state !== "loading") {
      request.terminalUpload = true;
    }
    const upload = this.record?.(observation);
    if (upload === undefined) {
      if (message.state !== "loading") {
        this.requests.delete(message.requestId);
      }
      return;
    }
    void upload
      .then(() => {
        if (request.terminalUpload && this.requests.get(message.requestId) === request) {
          this.requests.delete(message.requestId);
        }
      })
      .catch((error) => {
        if (request.terminalUpload && this.requests.get(message.requestId) === request) {
          this.requests.delete(message.requestId);
        }
        console.warn("Studio browser observation could not be recorded", error);
      });
  }

  clear(): void {
    this.requests.clear();
  }
}
