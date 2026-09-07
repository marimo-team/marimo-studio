import { flushSync } from "react-dom";

import { projectionHosts } from "../projections/host-runtime.ts";
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
import { stageShellSwap } from "./shell-swap.ts";
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
}

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
    let stagedShell: ReturnType<typeof stageShellSwap> | undefined;
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
          flushSync(() => commitRuntimeConfig(nextConfig));
          commitHistory(historyMode, historyUrl);
        } catch (error) {
          setSupportUrl(previousSupportUrl);
          try {
            flushSync(() => commitRuntimeConfig(previousConfig));
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
        };
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
        stagedShell = stageShellSwap(
          current,
          next,
          projectionHosts.stagePreservation(next, document),
        );
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
      const previousHistoryUrl = globalThis.location.href;
      const previousBase = document.baseURI;
      const nextBase = resolveDocumentBase(nextDocument, nextDocumentUrl);
      try {
        setSupportUrl(target.supportUrl);
        document.title = nextDocument.title;
        documentBase.set(nextBase);
        stagedStyles.commit();
        stagedViewStyles.commit();
        // Commit projection owners against the new document before the controller
        // rotates the capability-bound server transport.
        flushSync(() => {
          if (morphShell) {
            morphAuthoredShell(current, next);
            shellMorphed = true;
          } else if (stagedShell) {
            stagedShell.commit();
          }
          commitRuntimeConfig(nextConfig);
        });
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
        restore(() =>
          flushSync(() => {
            if (shellMorphed && previousShell) {
              const shell = previousShell;
              restore(() => morphAuthoredShell(current, shell));
            }
            restore(() => stagedShell?.rollback());
            restore(() => stagedViewStyles?.rollback());
            restore(() => stagedStyles?.rollback());
            restore(() => setSupportUrl(previousSupportUrl));
            restore(() => commitRuntimeConfig(previousConfig));
          }),
        );
        restore(() => {
          document.title = previousTitle;
        });
        restore(() =>
          globalThis.history.replaceState(globalThis.history.state, "", previousHistoryUrl),
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
      stagedShell?.finalize();
      stagedViewStyles.finalize();
      stagedStyles.finalize();
      this.documentUrl = nextDocumentUrl;
      this.authoredShell = nextAuthoredShell;
      stagedStyles = undefined;
      stagedViewStyles = undefined;
      stagedShell = undefined;
      scrollToFragment(historyUrl);
      return {
        target,
        supportChanged: previousSupportUrl !== target.supportUrl,
        reloadDocument: false,
      };
    } finally {
      stagedStyles?.discard();
      stagedViewStyles?.discard();
      stagedShell?.discard();
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
}
