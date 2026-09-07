import { DEFAULT_RUNTIME_ID } from "@marimo-studio/protocol/runtime-selection";

import type { fetchRuntimeControls } from "./control-remote.ts";

import {
  type ControlFrameConnector,
  type ControlEndpoint,
  type ControlSync,
  type ControlSyncStatus,
  synchronizeControlEndpoints,
} from "./control-sync.ts";
import { connectFrameControlBridge, type FrameControlEndpoint } from "./frame-bridge.ts";

const RETRY_DELAYS = [100, 250, 500, 1_000, 2_000, 5_000] as const;
const ATTEMPT_TIMEOUT_MS = 3_000;

interface ControlControllerOptions {
  runtime: string;
  editor: HTMLIFrameElement;
  preview: HTMLIFrameElement;
  supportUrl: () => string;
  clientId: () => string | undefined;
  connect?: ControlFrameConnector;
  connectPreview?: typeof connectFrameControlBridge;
  fetchControls: typeof fetchRuntimeControls;
  status?: (status: ControlSyncStatus, revision: string, sessionId: string | undefined) => void;
}

interface AttemptSignal {
  signal: AbortSignal;
  dispose(): void;
}

interface ControlRequest {
  controller: AbortController;
  editorSessionId: string | undefined;
  previewSessionId: string | undefined;
  revision: string;
}

const controlSetupError = (cause: unknown): Error =>
  cause instanceof Error ? cause : new Error(String(cause));

export class PreviewControlController {
  private sync: ControlSync | undefined;
  private syncRequest: ControlRequest | undefined;
  private revision: string | undefined;
  private editorSessionId: string | undefined;
  private previewSessionId: string | undefined;
  private request: ControlRequest | undefined;
  private retryTimer: ReturnType<typeof setTimeout> | undefined;
  private retryAttempt = 0;

  constructor(private readonly options: ControlControllerOptions) {}

  begin(
    revision: string,
    previewSessionId: string | undefined,
    editorSessionId: string | undefined,
  ): void {
    if (!this.options.connect || this.options.runtime === DEFAULT_RUNTIME_ID) {
      return;
    }
    if (
      (this.sync &&
        this.revision === revision &&
        this.previewSessionId === previewSessionId &&
        this.editorSessionId === editorSessionId) ||
      (this.request?.revision === revision &&
        this.request.previewSessionId === previewSessionId &&
        this.request.editorSessionId === editorSessionId)
    ) {
      return;
    }
    this.stop();
    void this.start(revision, previewSessionId, editorSessionId);
  }

  stop(): void {
    this.request?.controller.abort();
    this.request = undefined;
    this.sync?.dispose();
    this.sync = undefined;
    this.syncRequest = undefined;
    this.revision = undefined;
    this.editorSessionId = undefined;
    this.previewSessionId = undefined;
    if (this.retryTimer !== undefined) {
      clearTimeout(this.retryTimer);
      this.retryTimer = undefined;
    }
    this.retryAttempt = 0;
  }

  private async start(
    revision: string,
    previewSessionId: string | undefined,
    editorSessionId: string | undefined,
  ): Promise<void> {
    if (!this.options.connect || this.sync || this.request) {
      return;
    }
    const clientId = this.options.clientId();
    if (!editorSessionId || !clientId) {
      this.schedule(
        revision,
        previewSessionId,
        editorSessionId,
        new Error("The Marimo editor session is still connecting"),
      );
      return;
    }
    const controller = new AbortController();
    const request: ControlRequest = {
      controller,
      editorSessionId,
      previewSessionId,
      revision,
    };
    const attempt = attemptSignal(controller.signal);
    this.request = request;
    let retry = false;
    let failure: Error | undefined;
    let editor: ControlEndpoint | undefined;
    let preview: FrameControlEndpoint | undefined;
    let stopPreviewInputs = () => {};
    try {
      preview = (this.options.connectPreview ?? connectFrameControlBridge)(this.options.preview, {
        revision,
        runtime: this.options.runtime,
        sessionId: previewSessionId,
      });
      if (!preview) {
        retry = true;
        failure = new Error("Marimo control endpoints are still starting");
        return;
      }
      const previewControls = preview.metadata();
      if (previewControls === undefined) {
        retry = true;
        failure = new Error("Marimo control endpoints are still starting");
        return;
      }
      if (previewControls === null) {
        return;
      }
      const touched = new Set<string>();
      const previewBaseline = { metadata: previewControls, values: preview.snapshot(), touched };
      stopPreviewInputs = preview.subscribe((update) => {
        if (update.origin !== "registration") touched.add(update.objectId);
      });
      const editorConfig = await this.options.fetchControls(
        this.options.supportUrl(),
        clientId,
        editorSessionId,
        revision,
        attempt.signal,
      );
      if (attempt.signal.aborted || this.request !== request) {
        return;
      }
      if (editorConfig.revision !== revision) {
        retry = true;
        failure = new Error("Control configuration revisions have not converged");
        return;
      }
      editor = this.options.connect(this.options.editor);
      if (!editor) {
        retry = true;
        failure = new Error("Marimo control endpoints are still starting");
        return;
      }
      const connectedEditor = editor;
      const connectedPreview = preview;
      editor = undefined;
      preview = undefined;
      stopPreviewInputs();
      stopPreviewInputs = () => {};
      const sync = await synchronizeControlEndpoints({
        editor: connectedEditor,
        preview: connectedPreview,
        editorControls: editorConfig.controls,
        previewControls,
        previewBaseline,
        signal: attempt.signal,
        onStatus: (status) => {
          if (this.request === request || this.syncRequest === request) {
            this.options.status?.(status, revision, previewSessionId);
          }
        },
      });
      if (attempt.signal.aborted || this.request !== request) {
        sync.dispose();
        return;
      }
      this.sync = sync;
      this.syncRequest = request;
      this.revision = revision;
      this.editorSessionId = editorSessionId;
      this.previewSessionId = previewSessionId;
      this.retryAttempt = 0;
      this.options.status?.({ phase: "ready" }, revision, previewSessionId);
    } catch (cause) {
      if (!controller.signal.aborted && this.request === request) {
        retry = true;
        failure = controlSetupError(cause);
      }
    } finally {
      stopPreviewInputs();
      editor?.dispose();
      preview?.dispose();
      attempt.dispose();
      const ownsRequest = this.request === request;
      if (ownsRequest) {
        this.request = undefined;
      }
      if (retry && ownsRequest && !controller.signal.aborted) {
        this.schedule(revision, previewSessionId, editorSessionId, failure);
      }
    }
  }

  private schedule(
    revision: string,
    previewSessionId: string | undefined,
    editorSessionId: string | undefined,
    failure?: Error,
  ): void {
    if (this.retryTimer !== undefined || this.retryAttempt >= RETRY_DELAYS.length) {
      if (failure !== undefined && this.retryAttempt >= RETRY_DELAYS.length) {
        this.options.status?.({ phase: "degraded", error: failure }, revision, previewSessionId);
      }
      return;
    }
    const delay = RETRY_DELAYS[this.retryAttempt];
    this.retryAttempt += 1;
    this.retryTimer = setTimeout(() => {
      this.retryTimer = undefined;
      void this.start(revision, previewSessionId, editorSessionId);
    }, delay);
  }
}

const attemptSignal = (lifecycle: AbortSignal): AttemptSignal => {
  const controller = new AbortController();
  const cancel = () => controller.abort(lifecycle.reason);
  if (lifecycle.aborted) {
    cancel();
  } else {
    lifecycle.addEventListener("abort", cancel, { once: true });
  }
  const timeout = setTimeout(
    () => controller.abort(new DOMException("Control synchronization timed out", "TimeoutError")),
    ATTEMPT_TIMEOUT_MS,
  );
  return {
    signal: controller.signal,
    dispose: () => {
      clearTimeout(timeout);
      lifecycle.removeEventListener("abort", cancel);
    },
  };
};
