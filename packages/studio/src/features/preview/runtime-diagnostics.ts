import type {
  BrowserDiagnostic,
  RuntimeStatusPhase,
  RuntimeStatusReport,
} from "@marimo-studio/protocol/browser-observations";

const MAX_TRANSITIONS = 32;
const MAX_TRANSITION_DIAGNOSTICS = 20;

interface RuntimeDiagnosticsOptions {
  runtime: string;
  view: string;
  clock?: () => number;
  transitionLimit?: number;
}

interface RuntimeDiagnosticsUpdate {
  phase: RuntimeStatusPhase;
  diagnostics: readonly BrowserDiagnostic[];
  revision?: string | null;
  sessionId?: string | null;
}

const statusKey = (
  phase: RuntimeStatusPhase,
  diagnostics: readonly BrowserDiagnostic[],
  revision: string | null,
  sessionId: string | null,
): string => JSON.stringify({ phase, diagnostics, revision, sessionId });

const cloneDiagnostic = (diagnostic: BrowserDiagnostic): BrowserDiagnostic => {
  const cloned = { ...diagnostic };
  if (diagnostic.source !== undefined) {
    cloned.source = { ...diagnostic.source };
  }
  return cloned;
};

const cloneDiagnostics = (diagnostics: readonly BrowserDiagnostic[]): BrowserDiagnostic[] =>
  diagnostics.map(cloneDiagnostic);

export const cloneRuntimeStatusReport = (report: RuntimeStatusReport): RuntimeStatusReport => ({
  ...report,
  current: {
    ...report.current,
    diagnostics: cloneDiagnostics(report.current.diagnostics),
  },
  transitions: report.transitions.map((transition) => ({
    ...transition,
    diagnostics: cloneDiagnostics(transition.diagnostics),
  })),
});

export class RuntimeDiagnostics {
  private readonly runtime: string;
  private view: string;
  private revision: string | null = null;
  private sessionId: string | null = null;
  private current: RuntimeStatusReport["current"];
  private transitions: RuntimeStatusReport["transitions"] = [];
  private sequence = 0;
  private readonly clock: () => number;
  private readonly transitionLimit: number;

  constructor(options: RuntimeDiagnosticsOptions) {
    this.runtime = options.runtime;
    this.view = options.view;
    this.clock = options.clock ?? Date.now;
    this.transitionLimit = Math.min(
      Math.max(options.transitionLimit ?? MAX_TRANSITIONS, 1),
      MAX_TRANSITIONS,
    );
    this.current = { phase: "connecting", diagnostics: [] };
    this.append(this.current);
  }

  reset(view: string): RuntimeStatusReport {
    this.view = view;
    this.revision = null;
    this.sessionId = null;
    this.sequence = 0;
    this.transitions = [];
    this.current = { phase: "connecting", diagnostics: [] };
    this.append(this.current);
    return this.report();
  }

  record(update: RuntimeDiagnosticsUpdate): RuntimeStatusReport {
    const diagnostics = cloneDiagnostics(update.diagnostics);
    if (diagnostics.length > 200) {
      throw new RangeError("Runtime diagnostics accepts up to 200 current diagnostics");
    }
    if (
      (update.phase === "ready" && diagnostics.length > 0) ||
      ((update.phase === "degraded" || update.phase === "failed") && diagnostics.length === 0)
    ) {
      throw new TypeError(`Runtime phase ${update.phase} does not match its diagnostics`);
    }
    const next = { phase: update.phase, diagnostics };
    const revision = update.revision === undefined ? this.revision : update.revision;
    const sessionId = update.sessionId === undefined ? this.sessionId : update.sessionId;
    if (
      statusKey(this.current.phase, this.current.diagnostics, this.revision, this.sessionId) ===
      statusKey(next.phase, diagnostics, revision, sessionId)
    ) {
      this.current = next;
      return this.report();
    }
    this.revision = revision;
    this.sessionId = sessionId;
    this.current = next;
    this.append(next);
    return this.report();
  }

  report(): RuntimeStatusReport {
    return cloneRuntimeStatusReport({
      runtime: this.runtime,
      view: this.view,
      revision: this.revision,
      sessionId: this.sessionId,
      current: this.current,
      transitions: this.transitions,
    });
  }

  private append(status: RuntimeStatusReport["current"]): void {
    const diagnostics = cloneDiagnostics(status.diagnostics.slice(0, MAX_TRANSITION_DIAGNOSTICS));
    this.transitions = [
      ...this.transitions,
      {
        sequence: this.sequence++,
        observedAt: this.clock(),
        revision: this.revision,
        sessionId: this.sessionId,
        phase: status.phase,
        diagnostics,
        diagnosticsTruncated: diagnostics.length < status.diagnostics.length,
      },
    ].slice(-this.transitionLimit);
  }
}
