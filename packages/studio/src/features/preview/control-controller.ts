import { DEFAULT_RUNTIME_ID } from "@marimo-studio/protocol/runtime-selection";

import { fetchRuntimeControls } from "./control-remote.ts";
import {
  type ControlFrameConnector,
  type ControlSync,
  synchronizeControlEndpoints,
} from "./control-sync.ts";

const RETRY_DELAYS = [100, 250, 500, 1_000, 2_000, 5_000] as const;
const ATTEMPT_TIMEOUT_MS = 3_000;

interface ControlControllerOptions {
  runtime: string;
  editor: HTMLIFrameElement;
  preview: HTMLIFrameElement;
  supportUrl: () => string;
  connect?: ControlFrameConnector;
}

export class PreviewControlController {
  private sync: ControlSync | undefined;
  private revision: string | undefined;
  private sessionId: string | undefined;
  private request:
    | { controller: AbortController; revision: string; sessionId: string | undefined }
    | undefined;
  private retryTimer: ReturnType<typeof setTimeout> | undefined;
  private retryAttempt = 0;

  constructor(private readonly options: ControlControllerOptions) {}

  begin(revision: string, sessionId: string | undefined): void {
    if (!this.options.connect || this.options.runtime === DEFAULT_RUNTIME_ID) {
      return;
    }
    if (
      (this.sync && this.revision === revision && this.sessionId === sessionId) ||
      (this.request?.revision === revision && this.request.sessionId === sessionId)
    ) {
      return;
    }
    this.stop();
    void this.start(revision, sessionId);
  }

  stop(): void {
    this.request?.controller.abort();
    this.request = undefined;
    this.sync?.dispose();
    this.sync = undefined;
    this.revision = undefined;
    this.sessionId = undefined;
    if (this.retryTimer !== undefined) {
      clearTimeout(this.retryTimer);
      this.retryTimer = undefined;
    }
    this.retryAttempt = 0;
  }

  private async start(revision: string, sessionId: string | undefined): Promise<void> {
    if (!this.options.connect || this.sync || this.request) {
      return;
    }
    if (!sessionId) {
      this.schedule(
        revision,
        sessionId,
        new Error("The Marimo editor session is still connecting"),
      );
      return;
    }
    const controller = new AbortController();
    const request = { controller, revision, sessionId };
    const attempt = attemptSignal(controller.signal);
    this.request = request;
    let retry = false;
    let failure: unknown;
    try {
      await previewReady(this.options.preview, attempt.signal);
      if (attempt.signal.aborted || this.request !== request) {
        return;
      }
      const supportUrl = this.options.supportUrl();
      const [editorConfig, previewConfig] = await Promise.all([
        fetchRuntimeControls(supportUrl, DEFAULT_RUNTIME_ID, sessionId, attempt.signal),
        fetchRuntimeControls(supportUrl, this.options.runtime, sessionId, attempt.signal),
      ]);
      if (attempt.signal.aborted || this.request !== request) {
        return;
      }
      if (editorConfig.revision !== revision || editorConfig.revision !== previewConfig.revision) {
        retry = true;
        failure = new Error("Control configuration revisions have not converged");
        return;
      }
      if (!editorConfig.controls || !previewConfig.controls) {
        return;
      }
      const editor = this.options.connect(this.options.editor);
      const preview = this.options.connect(this.options.preview);
      if (!editor || !preview) {
        editor?.dispose();
        preview?.dispose();
        retry = true;
        failure = new Error("Marimo control endpoints are still starting");
        return;
      }
      const sync = await synchronizeControlEndpoints({
        editor,
        preview,
        editorControls: editorConfig.controls,
        previewControls: previewConfig.controls,
        signal: attempt.signal,
      });
      if (attempt.signal.aborted || this.request !== request) {
        sync.dispose();
        return;
      }
      this.sync = sync;
      this.revision = revision;
      this.sessionId = sessionId;
    } catch (error) {
      if (!controller.signal.aborted) {
        retry = true;
        failure = error;
      }
    } finally {
      attempt.dispose();
      if (this.request === request) {
        this.request = undefined;
      }
      if (retry && !controller.signal.aborted) {
        this.schedule(revision, sessionId, failure);
      }
    }
  }

  private schedule(revision: string, sessionId: string | undefined, failure?: unknown): void {
    if (this.retryTimer !== undefined || this.retryAttempt >= RETRY_DELAYS.length) {
      if (failure !== undefined && this.retryAttempt >= RETRY_DELAYS.length) {
        console.warn("Marimo control state could not be synchronized", failure);
      }
      return;
    }
    const delay = RETRY_DELAYS[this.retryAttempt];
    this.retryAttempt += 1;
    this.retryTimer = setTimeout(() => {
      this.retryTimer = undefined;
      void this.start(revision, sessionId);
    }, delay);
  }
}

const previewReady = async (frame: HTMLIFrameElement, signal: AbortSignal): Promise<void> => {
  const ready = (
    frame.contentWindow as (Window & { marimoStudio?: { ready(): Promise<void> } }) | null
  )?.marimoStudio?.ready;
  if (!ready) {
    return;
  }
  await abortable(ready(), signal);
};

const attemptSignal = (lifecycle: AbortSignal): { signal: AbortSignal; dispose: () => void } => {
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

const abortable = async <T>(operation: Promise<T>, signal: AbortSignal): Promise<T> => {
  signal.throwIfAborted();
  let cancel = () => {};
  const aborted = new Promise<never>((_resolve, reject) => {
    cancel = () => reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
    signal.addEventListener("abort", cancel, { once: true });
  });
  try {
    return await Promise.race([operation, aborted]);
  } finally {
    signal.removeEventListener("abort", cancel);
  }
};
