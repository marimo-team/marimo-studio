import type { RuntimeDescriptor } from "@marimo-studio/protocol/runtime-descriptor";

import { runtimeControlsSchema } from "@marimo-studio/protocol/runtime-config";

import type { fetchRuntimeControls, RuntimeControlSnapshot } from "./control-remote.ts";
import type {
  ControlFrameConnector,
  ControlSync,
  EndpointControlBindings,
} from "./control-types.ts";

import { RuntimeControlRequestError } from "./control-remote.ts";
import { synchronizeControlEndpoints } from "./control-sync.ts";
import {
  type ControlFrameConnector,
  type ControlSync,
  type ControlSyncStatus,
  synchronizeControlEndpoints,
} from "./control-sync.ts";
import { connectFrameControlBridge } from "./frame-bridge.ts";

const RETRY_DELAYS = [100, 250, 500, 1_000, 2_000, 5_000] as const;
const ATTEMPT_TIMEOUT_MS = 3_000;
const CONTROL_POLL_INTERVAL_MS = 1_000;
const SESSION_PENDING_RETRY_LIMIT = 3;

interface ControlControllerOptions {
  runtime: RuntimeDescriptor;
  peerRuntime: string | undefined;
  editor: HTMLIFrameElement;
  preview: HTMLIFrameElement;
  supportUrl: () => string;
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
  phase: "loading" | "synchronizing";
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
  private sessionPendingAttempts = 0;

  constructor(private readonly options: ControlControllerOptions) {}

  begin(
    revision: string,
    previewSessionId: string | undefined,
    editorSessionId: string | undefined,
  ): void {
    if (!this.options.connect || this.options.runtime === DEFAULT_RUNTIME_ID) {
      return;
    }
    const cacheContext = `${this.options.supportUrl()}\0${revision}\0${sessionId ?? ""}`;
    if (cacheContext !== this.controlCacheContext) {
      this.controlCacheContext = cacheContext;
      this.controlEtags.clear();
      this.controlSnapshots.clear();
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
    if (this.request?.phase === "synchronizing") {
      this.request.controller.abort();
    }
    this.request = undefined;
    const stopBindingSubscription = this.stopBindingSubscription;
    this.stopBindingSubscription = undefined;
    const sync = this.sync;
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
    this.sessionPendingAttempts = 0;

    const failures: unknown[] = [];
    const attempt = (operation: () => void) => {
      try {
        operation();
      } catch (error) {
        failures.push(error);
      }
    };
    if (pollController !== undefined) {
      attempt(() => pollController.abort());
    }
    if (pollTimer !== undefined) {
      attempt(() => clearTimeout(pollTimer));
    }
    if (requestController !== undefined) {
      attempt(() => requestController.abort());
    }
    if (stopBindingSubscription !== undefined) {
      attempt(stopBindingSubscription);
    }
    if (sync !== undefined) {
      attempt(() => sync.dispose());
    }
    if (retryTimer !== undefined) {
      attempt(() => clearTimeout(retryTimer));
    }
    if (failures.length === 1) {
      throw failures[0];
    }
    if (failures.length > 1) {
      throw new AggregateError(failures, "Marimo control synchronization cleanup failed");
    }
  }

  private async start(
    revision: string,
    previewSessionId: string | undefined,
    editorSessionId: string | undefined,
  ): Promise<void> {
    if (!this.options.connect || this.sync || this.request) {
      return;
    }
    if (!editorSessionId) {
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
      phase: "loading",
      previewSessionId,
      revision,
    };
    const attempt = attemptSignal(controller.signal);
    this.request = request;
    let retry = false;
    let failure: Error | undefined;
    try {
      const supportUrl = this.options.supportUrl();
      const [editorConfig, previewConfig] = await Promise.all([
        this.options.fetchControls(supportUrl, DEFAULT_RUNTIME_ID, editorSessionId, attempt.signal),
        this.options.fetchControls(
          supportUrl,
          this.options.runtime,
          editorSessionId,
          attempt.signal,
        ),
      ]);
      const editorConfig = editorRead.snapshot;
      const previewConfig = previewRead.snapshot;
      if (attempt.signal.aborted || this.request !== request) {
        return;
      }
      request.phase = "synchronizing";
      if (editorConfig.revision !== revision || editorConfig.revision !== previewConfig.revision) {
        retry = true;
        failure = new Error("Control configuration revisions have not converged");
        return;
      }
      const editor = this.options.connect(this.options.editor);
      const preview = (this.options.connectPreview ?? connectFrameControlBridge)(
        this.options.preview,
        {
          revision,
          runtime: this.options.runtime,
          sessionId: previewSessionId,
        },
      );
      if (!editor || !preview) {
        editor?.dispose();
        preview?.dispose();
        retry = true;
        failure = new Error("Marimo control endpoints are still starting");
        return;
      }
      const editorBindings = editor.controlBindings?.();
      const previewBindings = preview.controlBindings?.();
      const editorControls =
        editorConfig.controls ??
        (editorBindings === undefined
          ? undefined
          : runtimeControlsSchema.parse({ bindings: editorBindings }));
      const previewControls =
        previewConfig.controls ??
        (previewBindings === undefined
          ? undefined
          : runtimeControlsSchema.parse({ bindings: previewBindings }));
      if (
        !editorControls ||
        !previewControls ||
        !controlBindingsConverged(editorControls, previewControls)
      ) {
        editor.dispose();
        preview.dispose();
        retry = true;
        failure = new Error("Control bindings have not converged");
        return;
      }
      const sync = await synchronizeControlEndpoints({
        editor,
        preview,
        editorControls,
        previewControls,
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
      const bindingSubscriptions: Array<() => void> = [];
      const stopBindingSubscriptions = () => {
        const failures: unknown[] = [];
        for (const stop of bindingSubscriptions.splice(0)) {
          try {
            stop();
          } catch (error) {
            failures.push(error);
          }
        }
        if (failures.length === 1) {
          throw failures[0];
        }
        if (failures.length > 1) {
          throw new AggregateError(failures, "Control binding subscription cleanup failed");
        }
      };
      const refreshBindings = (source: "editor" | "preview", bindings: EndpointControlBindings) => {
        sync.invalidateControls(source);
        const controls = runtimeControlsSchema.parse({ bindings });
        void sync
          .updateControls(source === "editor" ? { editor: controls } : { preview: controls })
          .catch(() => {});
      };
      try {
        if (editorBindings !== undefined && editor.subscribeControlBindings !== undefined) {
          let currentBindings = editorBindings;
          bindingSubscriptions.push(
            editor.subscribeControlBindings((bindings) => {
              if (!sameControlBindings(currentBindings, bindings)) {
                currentBindings = bindings;
                refreshBindings("editor", bindings);
              }
            }),
          );
        }
        if (previewBindings !== undefined && preview.subscribeControlBindings !== undefined) {
          let currentBindings = previewBindings;
          bindingSubscriptions.push(
            preview.subscribeControlBindings((bindings) => {
              if (!sameControlBindings(currentBindings, bindings)) {
                currentBindings = bindings;
                refreshBindings("preview", bindings);
              }
            }),
          );
        }
      } catch (error) {
        const failures = [error];
        try {
          stopBindingSubscriptions();
        } catch (cleanupError) {
          failures.push(cleanupError);
        }
        try {
          sync.dispose();
        } catch (cleanupError) {
          failures.push(cleanupError);
        }
        if (failures.length === 1) {
          throw error;
        }
        throw new AggregateError(failures, "Control binding subscription setup failed");
      }
      this.stopBindingSubscription =
        bindingSubscriptions.length === 0 ? undefined : stopBindingSubscriptions;
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

  private async readControlSnapshot(
    supportUrl: string,
    runtime: string,
    sessionId: string,
    revision: string,
    clientId: string,
    signal: AbortSignal,
    force = false,
  ): Promise<ControlSnapshotRead> {
    const key = `${supportUrl}\0${runtime}\0${revision}\0${sessionId}`;
    const result = await this.options.fetchControls(
      supportUrl,
      runtime,
      sessionId,
      revision,
      clientId,
      force ? undefined : this.controlEtags.get(key),
      signal,
    );
    this.controlEtags.set(key, result.etag);
    if (result.kind === "changed") {
      const previous = this.controlSnapshots.get(key);
      this.controlSnapshots.set(key, result.snapshot);
      return {
        changed:
          previous === undefined ||
          !sameRuntimeControls(previous.controls, result.snapshot.controls),
        refreshed: true,
        snapshot: result.snapshot,
      };
    }
    const snapshot = this.controlSnapshots.get(key);
    if (!snapshot) {
      throw new Error("Control configuration returned 304 before its initial snapshot");
    }
    return { changed: false, refreshed: false, snapshot };
  }

  private scheduleControlPoll(context: ControlPollContext): void {
    if (!this.sync || this.pollTimer !== undefined) {
      return;
    }
    this.pollTimer = setTimeout(() => {
      this.pollTimer = undefined;
      void this.pollControls(context);
    }, CONTROL_POLL_INTERVAL_MS);
  }

  private async pollControls(context: ControlPollContext): Promise<void> {
    const sync = this.sync;
    if (!sync) {
      return;
    }
    const controller = new AbortController();
    const attempt = attemptSignal(controller.signal);
    const quarantineVersion = sync.quarantineVersion();
    const quarantinedSources = sync.quarantinedSources();
    this.pollController = controller;
    try {
      const results = await Promise.all([
        this.readControlSnapshot(
          context.supportUrl,
          context.peerRuntime,
          context.sessionId,
          context.revision,
          context.clientId,
          attempt.signal,
          quarantinedSources.has("editor"),
        ),
        this.readControlSnapshot(
          context.supportUrl,
          this.options.runtime.id,
          context.sessionId,
          context.revision,
          context.clientId,
          attempt.signal,
          quarantinedSources.has("preview"),
        ),
      ]);
      const changed = results.some((result) => result.changed);
      this.sessionPendingAttempts = 0;
      const refreshedQuarantine = Array.from(sync.quarantinedSources()).every((source) =>
        source === "editor" ? results[0].refreshed : results[1].refreshed,
      );
      if (
        this.sync === sync &&
        quarantineVersion === sync.quarantineVersion() &&
        (changed || (sync.isQuarantined() && refreshedQuarantine))
      ) {
        await sync.updateControls({
          editor: results[0].snapshot.controls,
          preview: results[1].snapshot.controls,
        });
      }
    } catch (error) {
      if (!controller.signal.aborted && !this.recoverRequestFailure(error)) {
        console.warn("Marimo control bindings poll failed", error);
      }
    } finally {
      attempt.dispose();
      if (this.pollController === controller) {
        this.pollController = undefined;
      }
    }
    if (controller.signal.aborted) {
      return;
    }
    this.scheduleControlPoll(context);
  }

  private recoverRequestFailure(error: UnparsedControlFailure): boolean {
    if (!(error instanceof RuntimeControlRequestError) || error.status !== 409) {
      return false;
    }
    if (error.code === "presentation-revision-unavailable") {
      this.rebootstrap(this.options.onContextUnavailable);
      return true;
    }
    if (error.code !== "runtime-sync-pending") {
      return false;
    }
    this.sessionPendingAttempts += 1;
    if (this.sessionPendingAttempts < SESSION_PENDING_RETRY_LIMIT) {
      return false;
    }
    this.rebootstrap(this.options.onContextUnavailable);
    return true;
  }

  private rebootstrap(callback: (() => void) | undefined): void {
    const failures: unknown[] = [];
    try {
      this.stop();
    } catch (error) {
      failures.push(error);
    }
    try {
      callback?.();
    } catch (error) {
      failures.push(error);
    }
    if (failures.length > 0) {
      console.warn(
        "Marimo control synchronization could not reload its preview",
        failures.length === 1 ? failures[0] : new AggregateError(failures),
      );
    }
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
