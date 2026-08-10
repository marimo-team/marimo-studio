import htmx from "htmx.org";

import { prepareCellHosts, syncPreservedCellHosts } from "../cells/host.ts";
import { prepareOutputHosts, syncPreservedOutputHosts } from "../outputs/host.ts";
import {
  commitRuntimeConfig,
  fetchRuntimeConfig,
  getRuntimeConfig,
  getSupportUrl,
  readResponseError,
  requireMatchingPresentationRevision,
  RuntimeConfigRequestError,
  setSupportUrl,
} from "../runtime-config/index.ts";
import { stageViewStyles, type StagedViewStyles } from "../view-styles/runtime.ts";
import { documentBase, resolveDocumentBase } from "./base.ts";
import { sameShellPresentation, type ShellTarget } from "./refresh-state.ts";
import { requiresDocumentReload } from "./scripts.ts";
import { abortError, PageStyles, type StagedStyles } from "./styles.ts";

export interface DocumentCommit {
  target: ShellTarget;
  supportChanged: boolean;
  reloadDocument: boolean;
}

export class PresentationDocument {
  private readonly styles = new PageStyles();
  private documentUrl = globalThis.location.href;

  constructor() {
    this.styles.mark(document);
  }

  get url(): string {
    return this.documentUrl;
  }

  abortStyles(): void {
    this.styles.abort();
  }

  refreshStylesheets(): Promise<void> {
    return this.styles.refresh(this.documentUrl);
  }

  async replace(
    nextDocumentUrl: string,
    nextSupportUrl: string,
    signal: AbortSignal,
    onTarget: (target: ShellTarget) => void,
  ): Promise<DocumentCommit> {
    let target = {
      documentUrl: nextDocumentUrl,
      supportUrl: nextSupportUrl,
    };
    onTarget(target);
    let stagedStyles: StagedStyles | undefined;
    let stagedViewStyles: StagedViewStyles | undefined;
    try {
      const response = await fetch(nextDocumentUrl, {
        cache: "no-store",
        headers: { Accept: "application/json" },
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
          `Shell refresh failed with ${response.status}`,
        );
        throw new RuntimeConfigRequestError(
          detail.message,
          detail.code,
          detail.transient,
          detail.hint,
        );
      }
      const nextConfig = await fetchRuntimeConfig(
        target.supportUrl,
        signal,
        getRuntimeConfig().runtime.id,
      );
      requireMatchingPresentationRevision(
        response.headers.get("Marimo-Studio-Revision"),
        nextConfig,
      );
      if (
        sameShellPresentation(
          this.currentPresentation(),
          this.targetPresentation(target, nextConfig.revision),
        )
      ) {
        await response.body?.cancel();
        this.documentUrl = nextDocumentUrl;
        return { target, supportChanged: false, reloadDocument: false };
      }

      const nextDocument = new DOMParser().parseFromString(await response.text(), "text/html");
      this.styles.mark(nextDocument);
      if (requiresDocumentReload(document, nextDocument)) {
        return {
          target,
          supportChanged: getSupportUrl() !== target.supportUrl,
          reloadDocument: true,
        };
      }
      const current = document.querySelector<HTMLElement>("#app-shell");
      const next = nextDocument.querySelector<HTMLElement>("#app-shell");
      if (!current || !next) {
        throw new Error("Shell refresh requires #app-shell");
      }
      prepareCellHosts(nextDocument);
      prepareOutputHosts(nextDocument);
      stagedViewStyles = await stageViewStyles(next);
      stagedStyles = await this.styles.stage(nextDocument, nextDocumentUrl, signal);
      if (signal.aborted) {
        throw abortError();
      }

      const previousSupportUrl = getSupportUrl();
      const previousConfig = getRuntimeConfig();
      const previousTitle = document.title;
      const previousDocumentUrl = this.documentUrl;
      const previousBase = document.baseURI;
      const nextBase = resolveDocumentBase(nextDocument, nextDocumentUrl);
      try {
        setSupportUrl(target.supportUrl);
        commitRuntimeConfig(nextConfig);
        document.title = nextDocument.title;
        globalThis.history.replaceState(globalThis.history.state, "", nextDocumentUrl);
        documentBase.set(nextBase);
        this.swap(current, next);
        syncPreservedCellHosts(next, document);
        syncPreservedOutputHosts(next, document);
        stagedStyles.commit();
        stagedViewStyles.commit();
      } catch (error) {
        setSupportUrl(previousSupportUrl);
        commitRuntimeConfig(previousConfig);
        document.title = previousTitle;
        globalThis.history.replaceState(globalThis.history.state, "", previousDocumentUrl);
        documentBase.set(previousBase);
        stagedStyles.discard();
        stagedViewStyles.discard();
        throw error;
      }
      this.documentUrl = nextDocumentUrl;
      stagedStyles = undefined;
      stagedViewStyles = undefined;
      return {
        target,
        supportChanged: previousSupportUrl !== target.supportUrl,
        reloadDocument: false,
      };
    } finally {
      stagedStyles?.discard();
      stagedViewStyles?.discard();
    }
  }

  private currentPresentation() {
    return {
      documentUrl: new URL(this.documentUrl, globalThis.location.href).href,
      supportUrl: new URL(getSupportUrl(), globalThis.location.href).href,
      revision: getRuntimeConfig().revision,
    };
  }

  private targetPresentation(target: ShellTarget, revision: string) {
    return {
      documentUrl: new URL(target.documentUrl, globalThis.location.href).href,
      supportUrl: new URL(target.supportUrl, globalThis.location.href).href,
      revision,
    };
  }

  private swap(current: HTMLElement, next: HTMLElement): void {
    const swap = (
      htmx as unknown as {
        swap: (target: Element, content: string, options: { swapStyle: string }) => void;
      }
    ).swap;
    swap(current, next.outerHTML, { swapStyle: "outerHTML" });
  }
}
