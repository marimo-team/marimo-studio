import htmx from "htmx.org";

import { projectionHosts, type StagedHostPreservation } from "../projections/host-runtime.ts";
import { clearProjectionBindingStale } from "../projections/staleness.ts";
import {
  commitRuntimeConfig,
  fetchRuntimeConfigForRevision,
  getRuntimeConfig,
  getSupportUrl,
  readResponseError,
  requireMatchingPresentationRevision,
  RuntimeConfigRequestError,
  setSupportUrl,
} from "../runtime-config/index.ts";
import { stageViewStyles, type StagedViewStyles } from "../view-styles/runtime.ts";
import { documentBase, resolveDocumentBase } from "./base.ts";
import { samePresentationRevision, type PresentationTarget } from "./presentation-refresh.ts";
import { presentationRefreshUrl, presentationRenewalSupportUrl } from "./refresh-url.ts";
import { requiresDocumentReload } from "./scripts.ts";
import { morphAuthoredShell, sameProjectionHostTopology } from "./shell-morph.ts";
import { abortError, PageStyles, type StagedStyles } from "./styles.ts";

type RevisionHistoryMode = "push" | "replace";

const commitHistory = (mode: RevisionHistoryMode, url: string): void => {
  if (mode === "push") {
    globalThis.history.pushState(globalThis.history.state, "", url);
  } else {
    globalThis.history.replaceState(globalThis.history.state, "", url);
  }
};

const scrollToFragment = (url: string): void => {
  const hash = new URL(url, globalThis.location.href).hash;
  if (!hash) {
    return;
  }
  let identifier = hash.slice(1);
  try {
    identifier = decodeURIComponent(identifier);
  } catch {
    // The browser retains malformed fragments as authored URL state.
  }
  const target = document.getElementById(identifier) ?? document.getElementsByName(identifier)[0];
  try {
    target?.scrollIntoView();
  } catch {
    return;
  }
};

export interface DocumentRevisionCommit {
  target: PresentationTarget;
  supportChanged: boolean;
  reloadDocument: boolean;
  finish(): void;
  rollback(): void;
}

const settledCommit = (
  commit: Omit<DocumentRevisionCommit, "finish" | "rollback">,
): DocumentRevisionCommit => ({ ...commit, finish: () => {}, rollback: () => {} });

const attempt = (failures: unknown[], action: () => void): void => {
  try {
    action();
  } catch (error) {
    failures.push(error);
  }
};

interface ProjectionAttributes {
  readonly attributes: readonly (readonly [string, string])[];
  readonly id: string;
  readonly localName: string;
}

interface ParkedProjectionHosts {
  readonly entries: readonly ParkedProjectionHost[];
  readonly pantry: HTMLElement;
}

interface ParkedProjectionHost {
  readonly host: HTMLElement;
  readonly placeholder: HTMLElement;
  placed: boolean;
}

const PRESERVED_HOST_SELECTOR =
  "marimo-cell[data-hx-preserve][id], marimo-output[data-hx-preserve][id]";

export class DocumentRevisionAdapter {
  private readonly styles = new PageStyles();
  private documentUrl: string;
  private authoredShell: string;

  constructor(
    private readonly presentationSessionId: string,
    private readonly runtimeSessionId: string,
  ) {
    this.documentUrl = presentationRefreshUrl(
      getRuntimeConfig(),
      globalThis.location.href,
      runtimeSessionId,
    );
    this.authoredShell = document.querySelector<HTMLElement>("#app-shell")?.outerHTML ?? "";
    this.styles.mark(document);
  }

  get url(): string {
    return this.documentUrl;
  }

  abort(): void {
    this.styles.abort();
  }

  async replace(
    nextDocumentUrl: string,
    nextSupportUrl: string,
    signal: AbortSignal,
    onTarget: (target: PresentationTarget) => void,
    historyMode: RevisionHistoryMode = "replace",
    historyUrl = nextDocumentUrl,
  ): Promise<DocumentRevisionCommit> {
    let target = {
      documentUrl: nextDocumentUrl,
      supportUrl: nextSupportUrl,
    };
    onTarget(target);
    let stagedStyles: StagedStyles | undefined;
    let stagedViewStyles: StagedViewStyles | undefined;
    let stagedHosts: StagedHostPreservation | undefined;
    let previousShell: HTMLElement | undefined;
    let shellMorphed = false;
    try {
      const response = await fetch(nextDocumentUrl, {
        cache: "no-store",
        headers: {
          Accept: "application/json",
          "Marimo-Studio-Preview-Session-Id": this.presentationSessionId,
        },
        signal,
      });
      const discoveredSupportUrl = response.headers.get("Marimo-Studio-Support-Url");
      if (discoveredSupportUrl) {
        target = {
          documentUrl: nextDocumentUrl,
          supportUrl: discoveredSupportUrl,
        };
        onTarget(target);
      }
      if (!response.ok) {
        const detail = await readResponseError(
          response,
          `Presentation refresh failed with ${response.status}`,
        );
        throw new RuntimeConfigRequestError(
          detail.message,
          detail.code,
          detail.transient,
          detail.hint,
        );
      }
      const revision = response.headers.get("Marimo-Studio-Revision");
      if (!revision) {
        throw new RuntimeConfigRequestError(
          "The view document did not identify its presentation revision.",
          "presentation-revision-missing",
          true,
          "Wait for the current view sources to settle.",
        );
      }
      const nextConfig = await fetchRuntimeConfigForRevision(
        presentationRenewalSupportUrl(nextDocumentUrl, target.supportUrl),
        revision,
        signal,
        getRuntimeConfig().runtime.id,
        this.presentationSessionId,
        this.runtimeSessionId,
      );
      await this.requireCurrentRevision(nextDocumentUrl, nextConfig, signal);
      if (
        samePresentationRevision(
          this.currentPresentation(),
          this.targetPresentation(target, nextConfig.revision),
        )
      ) {
        await response.arrayBuffer();
        const previousSupportUrl = getSupportUrl();
        const previousConfig = getRuntimeConfig();
        const previousHistoryUrl = globalThis.location.href;
        try {
          setSupportUrl(target.supportUrl);
          commitRuntimeConfig(nextConfig);
          commitHistory(historyMode, historyUrl);
        } catch (error) {
          setSupportUrl(previousSupportUrl);
          try {
            commitRuntimeConfig(previousConfig);
          } catch {
            // Runtime config assignment precedes listener notification.
          }
          globalThis.history.replaceState(globalThis.history.state, "", previousHistoryUrl);
          throw error;
        }
        if (nextConfig.projectionRevision !== previousConfig.projectionRevision) {
          clearProjectionBindingStale(nextConfig.projectionRevision);
        }
        scrollToFragment(historyUrl);
        this.documentUrl = nextDocumentUrl;
        return {
          target,
          supportChanged: previousSupportUrl !== target.supportUrl,
          reloadDocument: false,
        };
      }

      const nextDocument = new DOMParser().parseFromString(await response.text(), "text/html");
      this.styles.mark(nextDocument);
      const current = document.querySelector<HTMLElement>("#app-shell");
      const parsedNext = nextDocument.querySelector<HTMLElement>("#app-shell");
      if (!current || !parsedNext) {
        throw new Error("Presentation refresh requires #app-shell");
      }
      const nextAuthoredShell = parsedNext.outerHTML;
      const shellChanged = this.authoredShell !== nextAuthoredShell;
      if (requiresDocumentReload(document, nextDocument, shellChanged)) {
        return {
          target,
          supportChanged: getSupportUrl() !== target.supportUrl,
          reloadDocument: true,
        });
      }
      const projectionChanged =
        getRuntimeConfig().projectionRevision !== nextConfig.projectionRevision;
      projectionHosts.prepare(nextDocument);
      const next = document.importNode(parsedNext, true);
      const morphShell =
        shellChanged && !projectionChanged && sameProjectionHostTopology(current, next);
      if (shellChanged && !projectionChanged && !morphShell) {
        return {
          target,
          supportChanged: getSupportUrl() !== target.supportUrl,
          reloadDocument: true,
        };
      }
      stagedViewStyles = await stageViewStyles(next);
      stagedStyles = await this.styles.stage(nextDocument, nextDocumentUrl, signal);
      if (shellChanged && !morphShell) {
        stagedHosts = projectionHosts.stagePreservation(next, document);
      }
      if (morphShell) {
        const clonedShell = current.cloneNode(true);
        if (!(clonedShell instanceof HTMLElement)) {
          throw new Error("Unable to snapshot the current presentation shell");
        }
        previousShell = clonedShell;
      }
      if (signal.aborted) {
        throw abortError();
      }

      const previousSupportUrl = getSupportUrl();
      const previousConfig = getRuntimeConfig();
      const previousTitle = document.title;
      const previousDocumentUrl = this.documentUrl;
      const previousBase = document.baseURI;
      const projectionAttributes = this.captureProjectionAttributes(current);
      const activeElement = document.activeElement;
      const focused =
        activeElement instanceof HTMLElement && current.contains(activeElement)
          ? activeElement
          : undefined;
      const scroll = { x: globalThis.scrollX, y: globalThis.scrollY };
      const nextBase = resolveDocumentBase(nextDocument, nextDocumentUrl);
      const committedStyles = stagedStyles;
      const committedViewStyles = stagedViewStyles;
      let restorePageStyles = () => {};
      let restoreViewStyles = () => {};
      let restored = false;
      let inFlightParked: ParkedProjectionHosts | undefined;
      const restore = () => {
        if (restored) {
          return;
        }
        restored = true;
        const failures: unknown[] = [];
        attempt(failures, () => {
          const active = document.querySelector<HTMLElement>("#app-shell");
          if (active && active !== current) {
            if (inFlightParked !== undefined) {
              this.reparkPlacedHosts(inFlightParked);
            }
            active.replaceWith(current);
          }
          if (inFlightParked !== undefined) {
            this.restoreParkedHosts(inFlightParked);
            inFlightParked = undefined;
          }
        });
        attempt(failures, () => setSupportUrl(previousSupportUrl));
        attempt(failures, () => {
          commitRuntimeConfig(previousConfig);
        });
        attempt(failures, () => {
          document.title = previousTitle;
        });
        attempt(failures, () => {
          globalThis.history.replaceState(globalThis.history.state, "", previousDocumentUrl);
        });
        attempt(failures, () => documentBase.set(previousBase));
        attempt(failures, restoreViewStyles);
        attempt(failures, restorePageStyles);
        attempt(failures, () => projectionHosts.prepare(document));
        attempt(failures, () => this.restoreProjectionAttributes(projectionAttributes));
        attempt(failures, () => focused?.focus());
        attempt(failures, () => {
          if (globalThis.scrollX !== scroll.x || globalThis.scrollY !== scroll.y) {
            globalThis.scrollTo(scroll.x, scroll.y);
          }
        });
        this.documentUrl = previousDocumentUrl;
        if (failures.length > 0) {
          throw new AggregateError(failures, "Document revision rollback failed.");
        }
      };
      try {
        setSupportUrl(target.supportUrl);
        commitRuntimeConfig(nextConfig);
        document.title = nextDocument.title;
        documentBase.set(nextBase);
        stagedStyles.commit();
        stagedViewStyles.commit();
        if (morphShell) {
          morphAuthoredShell(current, next);
          shellMorphed = true;
        } else if (stagedHosts) {
          this.swap(current, next, stagedHosts);
        }
        commitHistory(historyMode, historyUrl);
      } catch (error) {
        const rollbackErrors: unknown[] = [];
        const restore = (operation: () => void) => {
          try {
            operation();
          } catch (rollbackError) {
            rollbackErrors.push(rollbackError);
          }
        };
        if (shellMorphed && previousShell) {
          const shell = previousShell;
          restore(() => morphAuthoredShell(current, shell));
        }
        restore(() => stagedHosts?.rollback());
        restore(() => stagedViewStyles?.rollback());
        restore(() => stagedStyles?.rollback());
        restore(() => setSupportUrl(previousSupportUrl));
        restore(() => commitRuntimeConfig(previousConfig));
        restore(() => {
          document.title = previousTitle;
        });
        restore(() =>
          globalThis.history.replaceState(globalThis.history.state, "", previousDocumentUrl),
        );
        restore(() => documentBase.set(previousBase));
        if (rollbackErrors.length > 0) {
          throw new AggregateError(
            [error, ...rollbackErrors],
            "Presentation commit and rollback failed",
          );
        }
        throw error;
      }
      stagedHosts?.finalize();
      stagedViewStyles.finalize();
      stagedStyles.finalize();
      this.documentUrl = nextDocumentUrl;
      this.authoredShell = nextAuthoredShell;
      stagedStyles = undefined;
      stagedViewStyles = undefined;
      stagedHosts = undefined;
      scrollToFragment(historyUrl);
      return {
        target,
        supportChanged: previousSupportUrl !== target.supportUrl,
        reloadDocument: false,
        finish: () => {
          if (!finished) {
            if (inFlightParked !== undefined) {
              this.finishParkedHosts(inFlightParked);
              inFlightParked = undefined;
            }
            finished = true;
          }
        },
        rollback: () => {
          if (!finished) {
            restore();
            finished = true;
          }
        },
      };
    } finally {
      stagedStyles?.discard();
      stagedViewStyles?.discard();
      stagedHosts?.discard();
    }
  }

  private currentPresentation() {
    return {
      documentUrl: new URL(this.documentUrl, globalThis.location.href).href,
      supportUrl: new URL(getSupportUrl(), globalThis.location.href).href,
      revision: getRuntimeConfig().revision,
    };
  }

  private targetPresentation(target: PresentationTarget, revision: string) {
    return {
      documentUrl: new URL(target.documentUrl, globalThis.location.href).href,
      supportUrl: new URL(target.supportUrl, globalThis.location.href).href,
      revision,
    };
  }

  private async requireCurrentRevision(
    documentUrl: string,
    config: ReturnType<typeof getRuntimeConfig>,
    signal: AbortSignal,
  ): Promise<void> {
    const response = await fetch(documentUrl, {
      cache: "no-store",
      headers: {
        "Marimo-Studio-Preview-Session-Id": this.presentationSessionId,
      },
      method: "HEAD",
      signal,
    });
    if (!response.ok) {
      const detail = await readResponseError(
        response,
        `Presentation revision check failed with ${response.status}`,
      );
      throw new RuntimeConfigRequestError(
        detail.message,
        detail.code,
        detail.transient,
        detail.hint,
      );
    }
    requireMatchingPresentationRevision(response.headers.get("Marimo-Studio-Revision"), config);
  }

  private swap(current: HTMLElement, next: HTMLElement, hosts: StagedHostPreservation): void {
    current.before(next);
    try {
      hosts.commit();
    } catch (error) {
      next.remove();
      throw error;
    }
    current.remove();
    try {
      htmx.process(next);
    } catch {
      // The committed document remains usable when optional htmx setup fails.
    }
  }
}
