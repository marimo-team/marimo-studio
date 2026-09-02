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
  private pending: PendingObservation | undefined;

  constructor(
    private readonly runtime: string,
    private readonly preview: HTMLIFrameElement,
    private readonly accept: AcceptObservation,
    private readonly record?: RecordBrowserObservation,
  ) {}

  request(request: ObserveViewRequest, lifecycleId: number): void {
    if (request.runtime !== this.runtime) {
      return;
    }
    this.pending = {
      message: {
        type: "marimo-studio:observe-view",
        runtime: request.runtime,
        lifecycleId,
        view: request.view,
        revision: request.revision,
        runtimeInstance: request.runtimeInstance,
        requestId: request.requestId,
      },
      terminalUpload: false,
    };
    this.post();
  }

  post(): void {
    const request = this.pending;
    if (request && !request.terminalUpload) {
      this.preview.contentWindow?.postMessage(request.message, "*");
    }
  }

  receive(message: ViewObservationMessage): void {
    const request = this.pending;
    const expected = request?.message;
    if (
      request === undefined ||
      expected === undefined ||
      expected.requestId !== message.requestId ||
      request.terminalUpload ||
      expected.lifecycleId !== message.lifecycleId ||
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
      projectionInstances: message.projectionInstances,
      runtimeStatus,
    };
    if (message.state !== "loading") {
      request.terminalUpload = true;
    }
    const upload = this.record?.(observation);
    if (upload === undefined) {
      if (message.state !== "loading" && this.pending === request) {
        this.pending = undefined;
      }
      return;
    }
    void upload
      .then(() => {
        if (request.terminalUpload && this.pending === request) {
          this.pending = undefined;
        }
      })
      .catch((error) => {
        if (request.terminalUpload && this.pending === request) {
          this.pending = undefined;
        }
        console.warn("Studio browser observation could not be recorded", error);
      });
  }

  clear(): void {
    this.pending = undefined;
  }
}
