import type { ProjectionRequest } from "@marimo-studio/protocol/projections";
import type { RuntimeConfig } from "@marimo-studio/protocol/runtime-config";

import { parseErrorResponse } from "@marimo-studio/protocol/errors";
import { isRenderSource } from "@marimo-studio/protocol/projections";
import {
  renderIndexSchema,
  renderBundleSchema,
  type RenderIndex,
  type RenderRequest,
  type RenderBundle,
} from "@marimo-studio/protocol/render";
import { appendUrlPath } from "@marimo-studio/protocol/url";
import {
  projectDiagnosticSchema,
  type ProjectDiagnostic,
} from "@marimo-studio/protocol/view-project";
import { z } from "zod";

import type { OutputHostState } from "../outputs/host.ts";
import type { RenderReads } from "./inputs.ts";

import { errorMessage } from "../errors.ts";
import { responseJsonOrNull } from "../json.ts";
import { notifyProjectionChanged } from "../projections/changes.ts";
import { readiness } from "../readiness.ts";
import {
  getRuntimeConfig,
  hasRuntimeConfig,
  subscribeRuntimeConfig,
} from "../runtime-config/index.ts";
import {
  getPreparedState,
  getRenderInputReader,
  RenderInputError,
  subscribeRenderInputs,
} from "./inputs.ts";
import { RenderView, type RenderRecord } from "./view.ts";

export type { RenderFileRecord, RenderRecord } from "./view.ts";

/** The `marimo-output-error` detail of a render host. */
export interface RenderErrorDetail {
  readonly render: string;
  readonly code: string;
  readonly message: string;
  readonly hint: string;
  readonly diagnostics: readonly ProjectDiagnostic[];
}

type Outcome =
  | { readonly kind: "result"; readonly result: RenderBundle }
  | { readonly kind: "failure"; readonly diagnostics: readonly ProjectDiagnostic[] }
  | { readonly kind: "transient"; readonly diagnostics: readonly ProjectDiagnostic[] }
  | { readonly kind: "waiting" };

// Results settle in bursts, so a short delay folds them into one request.
const RENDER_DELAY_MS = 150;
const RETRY_DELAYS_MS = [250, 500, 1_000, 2_000, 4_000] as const;
const diagnosticsSchema = z.array(projectDiagnosticSchema);
const hosts = new Set<HTMLElement>();
const indexes = new Map<string, Promise<RenderIndex | null>>();

const problem = (code: string, message: string, hint = ""): ProjectDiagnostic => ({
  code,
  severity: "error",
  message,
  hint,
  source: null,
});

const unavailable = (): ProjectDiagnostic =>
  problem(
    "render-results-unavailable",
    "This page has no notebook results to render this file with.",
    "Open the view with the Python runtime or in Studio's edit mode, or export it with the zero-python runtime.",
  );

const recoveryHint = (status: number): string => {
  if (status === 404) {
    return "Rebuild the view to publish its renders, then reload the page.";
  }
  if (status === 401 || status === 403) {
    return "Reload the page to open the view with current access.";
  }
  return "Reload the page. If rendering still fails, check the Studio server log.";
};

const sleep = (milliseconds: number) =>
  new Promise<void>((resolve) => setTimeout(resolve, milliseconds));

/** Return the reads of `render`, one projection request per read site. */
const renderReads = (config: RuntimeConfig, render: string): RenderReads => {
  const reads: Record<"value" | "output" | "cell", ProjectionRequest[]> = {
    value: [],
    output: [],
    cell: [],
  };
  for (const site of config.sites) {
    const target = site.targets?.[0];
    if (site.render === render && target !== undefined) {
      reads[site.kind].push({ siteId: site.id, instanceId: `render:${render}:${site.id}`, target });
    }
  }
  return {
    revision: config.revision,
    values: reads.value,
    outputs: reads.output,
    cells: reads.cell,
  };
};

const fileUrl = (supportUrl: string, bundle: string, path: string): string =>
  appendUrlPath(
    supportUrl,
    ["renders", bundle, ...path.split("/")].map((segment) => encodeURIComponent(segment)).join("/"),
  );

const renderRecord = (result: RenderBundle, supportUrl: string): RenderRecord =>
  Object.freeze({
    render: result.render,
    bundle: result.bundle,
    main: result.main,
    preview: result.preview,
    files: Object.freeze(
      result.files.map((file) =>
        Object.freeze({
          path: file.path,
          mediaType: file.mediaType,
          size: file.size,
          url: fileUrl(supportUrl, result.bundle, file.path),
        }),
      ),
    ),
    warnings: Object.freeze([...result.warnings]),
    absent: Object.freeze([...result.absent]),
  });

/** Load a static export's `renders/index.json` once per revision. */
const renderIndex = (config: RuntimeConfig): Promise<RenderIndex | null> => {
  const key = `${config.revision}\0${config.supportUrl}`;
  const cached = indexes.get(key);
  if (cached) {
    return cached;
  }
  const loading = (async () => {
    const response = await fetch(appendUrlPath(config.supportUrl, "renders/index.json"));
    const parsed = response.ok
      ? renderIndexSchema.safeParse(await responseJsonOrNull(response))
      : undefined;
    return parsed?.success ? parsed.data : null;
  })().catch(() => null);
  indexes.set(key, loading);
  // Only a loaded index stays cached, so a page without one asks again later.
  void loading.then((loaded) => {
    if (loaded === null && indexes.get(key) === loading) {
      indexes.delete(key);
    }
  });
  return loading;
};

/**
 * Return the fingerprint of the prepared state the page shows. A view whose
 * renders read no notebook results exports one state.
 */
const currentState = (index: RenderIndex): string | undefined => {
  const shown = getPreparedState()?.();
  if (shown !== undefined) {
    return shown;
  }
  const fingerprints = Object.keys(index.states);
  return fingerprints.length === 1 ? fingerprints[0] : undefined;
};

/**
 * Show one render of the view inside a `<marimo-output render>` host, and
 * request it again whenever the notebook may have produced new results.
 *
 * Studio renders on the server. With the Python runtime it reads the
 * render's inputs from the reader's kernel. Browser runtimes in edit mode
 * post the inputs they compute, and a static export looks up the bundle
 * rendered for the prepared state the reader is viewing.
 */
export class RenderHost {
  private readonly view: RenderView;
  private record?: RenderRecord;
  private request?: AbortController;
  private timer?: ReturnType<typeof setTimeout>;
  private queued = false;
  private running = false;
  private active = false;
  private failing = false;
  private revision?: string;
  private sessionId?: string;
  private release: (() => void)[] = [];

  constructor(
    private readonly host: HTMLElement,
    readonly source: string,
    root: ShadowRoot,
  ) {
    this.view = new RenderView(root);
  }

  /** The last bundle this host showed. */
  get current(): RenderRecord | undefined {
    return this.record;
  }

  connect(): void {
    if (this.active) {
      return;
    }
    this.active = true;
    hosts.add(this.host);
    this.setState("connecting");
    if (!isRenderSource(this.source) || this.host.hasAttribute("value")) {
      this.fail([
        problem(
          "render-host-invalid",
          `<marimo-output render="${this.source}"> needs a project file and no value attribute.`,
          'Name the file the view renders, such as render="main.typ", and show values in another host.',
        ),
      ]);
      return;
    }
    const configChanged = () => {
      const config = getRuntimeConfig();
      if (config.revision !== this.revision || config.presentationSessionId !== this.sessionId) {
        this.schedule(true);
      }
    };
    const connectionChanged = (
      snapshot: ReturnType<typeof readiness.snapshot>,
      previous: ReturnType<typeof readiness.snapshot>,
    ) => {
      if (snapshot.connection === "ready" && previous.connection !== "ready") {
        this.schedule();
      }
    };
    const resized = () => this.view.resize();
    let stopResize: () => void;
    if ("ResizeObserver" in globalThis) {
      const observer = new ResizeObserver(resized);
      observer.observe(this.view.observedElement());
      stopResize = () => observer.disconnect();
    } else {
      globalThis.addEventListener("resize", resized);
      stopResize = () => globalThis.removeEventListener("resize", resized);
    }
    this.release = [
      subscribeRuntimeConfig(configChanged),
      subscribeRenderInputs(() => this.schedule()),
      readiness.subscribe(connectionChanged),
      stopResize,
    ];
    this.schedule();
  }

  disconnect(): void {
    if (!this.active) {
      return;
    }
    this.active = false;
    hosts.delete(this.host);
    this.release.forEach((release) => release());
    this.release = [];
    clearTimeout(this.timer);
    this.timer = undefined;
    this.queued = false;
    this.request?.abort();
    this.request = undefined;
    this.view.destroy();
    this.record = undefined;
    this.failing = false;
    this.revision = undefined;
    this.sessionId = undefined;
    delete this.host.dataset.state;
    this.host.removeAttribute("aria-busy");
    this.clearDiagnostic();
    notifyProjectionChanged();
  }

  /**
   * Request the render again. A superseding request aborts the one in flight,
   * and otherwise a request in flight queues one more after it.
   */
  private schedule(supersede = false): void {
    if (!this.active) {
      return;
    }
    if (supersede) {
      this.request?.abort();
    }
    // Readiness waits for the pending request from the moment it is due, so
    // a reader that awaits the page never sees the previous bundle as current.
    if (this.record) {
      this.setState("stale");
    }
    this.queued = true;
    if (this.running || this.timer !== undefined) {
      return;
    }
    this.timer = setTimeout(() => {
      this.timer = undefined;
      void this.drain();
    }, RENDER_DELAY_MS);
  }

  private async drain(): Promise<void> {
    this.running = true;
    try {
      let retries = 0;
      while (this.queued && this.active) {
        this.queued = false;
        const transient = await this.attempt();
        if (transient === undefined) {
          retries = 0;
          continue;
        }
        const delay = RETRY_DELAYS_MS[retries];
        if (delay === undefined) {
          retries = 0;
          this.fail(transient);
          continue;
        }
        retries += 1;
        await sleep(delay);
        this.queued = true;
      }
    } finally {
      this.running = false;
    }
  }

  /** Request and show the render once. Returns diagnostics when a retry may succeed. */
  private async attempt(): Promise<readonly ProjectDiagnostic[] | undefined> {
    if (!hasRuntimeConfig() || readiness.snapshot().connection !== "ready") {
      return undefined;
    }
    const config = getRuntimeConfig();
    this.revision = config.revision;
    this.sessionId = config.presentationSessionId;
    const controller = new AbortController();
    this.request = controller;
    const { signal } = controller;
    try {
      const outcome = await this.resolve(config, signal);
      if (signal.aborted || outcome.kind === "waiting") {
        return undefined;
      }
      if (outcome.kind === "transient") {
        return outcome.diagnostics;
      }
      if (outcome.kind === "failure") {
        this.fail(outcome.diagnostics);
        return undefined;
      }
      const record = renderRecord(outcome.result, config.supportUrl);
      try {
        await this.view.show(record, signal);
      } catch (error) {
        if (!signal.aborted) {
          this.fail([problem("render-file-unavailable", errorMessage(error))]);
        }
        return undefined;
      }
      this.succeed(record);
      return undefined;
    } catch (error) {
      // A failed read waits for the notebook's next results.
      if (!signal.aborted) {
        this.fail(
          error instanceof RenderInputError
            ? error.diagnostics
            : [problem("render-inputs-unavailable", errorMessage(error))],
        );
      }
      return undefined;
    } finally {
      if (this.request === controller) {
        this.request = undefined;
      }
    }
  }

  private async resolve(config: RuntimeConfig, signal: AbortSignal): Promise<Outcome> {
    if (config.runtime.id === "server") {
      this.begin();
      return this.post(config, { revision: config.revision, render: this.source }, signal);
    }
    if (config.mode !== "edit") {
      this.begin();
      const index = await renderIndex(config);
      const state = index === null ? undefined : currentState(index);
      const result = state === undefined ? undefined : index?.states[state]?.[this.source];
      return result
        ? { kind: "result", result }
        : { kind: "failure", diagnostics: [unavailable()] };
    }
    const read = getRenderInputReader();
    if (!read) {
      return { kind: "waiting" };
    }
    this.begin();
    const inputs = await read(this.source, renderReads(config, this.source), signal);
    signal.throwIfAborted();
    if (inputs === undefined) {
      return { kind: "waiting" };
    }
    return this.post(
      config,
      {
        revision: config.revision,
        render: this.source,
        values: inputs.values,
        outputs: inputs.outputs,
        cells: inputs.cells,
      },
      signal,
    );
  }

  private async post(
    config: RuntimeConfig,
    body: RenderRequest,
    signal: AbortSignal,
  ): Promise<Outcome> {
    const headers = new Headers({ "Content-Type": "application/json" });
    if (config.presentationSessionId) {
      headers.set("Marimo-Session-Id", config.presentationSessionId);
    }
    let response: Response;
    try {
      response = await fetch(appendUrlPath(config.supportUrl, "render"), {
        method: "POST",
        headers,
        body: JSON.stringify(body),
        signal,
      });
    } catch (error) {
      signal.throwIfAborted();
      // A dropped connection is transient, so the render retries.
      return {
        kind: "transient",
        diagnostics: [
          problem(
            "render-network-failed",
            errorMessage(error),
            "Check that the Studio server is running.",
          ),
        ],
      };
    }
    const payload = await responseJsonOrNull(response);
    if (response.ok) {
      const parsed = renderBundleSchema.safeParse(payload);
      return parsed.success && parsed.data.render === this.source
        ? { kind: "result", result: parsed.data }
        : {
            kind: "failure",
            diagnostics: [
              problem("render-response-invalid", "The Studio server sent an invalid render."),
            ],
          };
    }
    const detail = parseErrorResponse(payload);
    const diagnostics = diagnosticsSchema.safeParse(detail.diagnostics);
    if (diagnostics.success && diagnostics.data.length > 0) {
      return { kind: "failure", diagnostics: diagnostics.data };
    }
    const failure = [
      problem(
        detail.error ?? "render-request-failed",
        detail.message ?? `Rendering failed with ${response.status}.`,
        detail.hint ?? recoveryHint(response.status),
      ),
    ];
    return detail.transient === true
      ? { kind: "transient", diagnostics: failure }
      : { kind: "failure", diagnostics: failure };
  }

  /** Mark a request in flight, keeping the shown bundle as stale. */
  private begin(): void {
    this.view.setStatus("Rendering…");
    this.setState(this.record ? "stale" : "loading");
  }

  private succeed(record: RenderRecord): void {
    const previous = this.record;
    this.record = record;
    this.failing = false;
    this.clearDiagnostic();
    this.view.showProblems(record.warnings);
    this.view.setStatus(
      record.absent.length > 0 ? `Showing the default for ${record.absent.join(", ")}.` : "",
    );
    this.setState("ready");
    if (previous?.bundle !== record.bundle) {
      this.host.dispatchEvent(
        new CustomEvent(previous ? "marimo-output-updated" : "marimo-output-ready", {
          bubbles: true,
          composed: true,
          detail: record,
        }),
      );
    }
  }

  /** Report `diagnostics`, keeping the last bundle on screen. */
  private fail(diagnostics: readonly ProjectDiagnostic[]): void {
    const first = diagnostics[0] ?? problem("render-failed", "The render failed.");
    const detail: RenderErrorDetail = {
      render: this.source,
      code: first.code,
      message: first.message,
      hint: first.hint,
      diagnostics,
    };
    const entering = !this.failing;
    this.failing = true;
    this.view.showProblems(diagnostics);
    this.view.setStatus("");
    this.host.dataset.marimoDiagnosticCode = detail.code;
    this.host.dataset.marimoDiagnosticMessage = detail.message;
    this.host.dataset.marimoDiagnosticHint = detail.hint;
    this.setState("error");
    // Like a value host, a render host reports the first transition into its
    // error state. Each request passes through loading or stale, so failures
    // since the last bundle count as one transition.
    if (entering) {
      this.host.dispatchEvent(
        new CustomEvent("marimo-output-error", { bubbles: true, composed: true, detail }),
      );
    }
  }

  private clearDiagnostic(): void {
    delete this.host.dataset.marimoDiagnosticCode;
    delete this.host.dataset.marimoDiagnosticMessage;
    delete this.host.dataset.marimoDiagnosticHint;
  }

  private setState(state: OutputHostState): void {
    if (this.host.dataset.state === state) {
      return;
    }
    this.host.dataset.state = state;
    this.host.toggleAttribute("aria-busy", state !== "ready" && state !== "error");
    notifyProjectionChanged();
  }
}

/** Return the connected render hosts. */
export const getRenderHosts = (): readonly HTMLElement[] => Array.from(hosts);
