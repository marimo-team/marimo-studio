import { beginPresentationRefresh, setPresentationRefreshState } from "../readiness.ts";

const APP_SHELL = "#app-shell";
const OUTPUT_BOUNDARY = "[data-marimo-cell-output]";
const RUNTIME_STYLE = "data-marimo-studio-runtime";
const VIEW_STYLE = "data-marimo-studio-view-utilities";

declare global {
  var __MARIMO_STUDIO_STYLE_TIMEOUT__: ReturnType<typeof setTimeout> | undefined;
}

export interface StagedViewStyles {
  commit(): void;
  rollback(): void;
  finalize(): void;
  discard(): void;
}

type GenerateViewCss = (tokens: ReadonlySet<string>) => Promise<string>;

let controller: ViewStyleController | undefined;
let currentDiagnostic: ViewStyleDiagnostic | undefined;
let ownedDiagnosticHost: HTMLElement | undefined;

const appShell = (): HTMLElement | undefined =>
  document.querySelector<HTMLElement>(APP_SHELL) ?? undefined;

const classTokens = (element: Element): string[] => Array.from(element.classList).filter(Boolean);

export const collectViewClassTokens = (root: Element): Set<string> => {
  const tokens = new Set<string>();
  const visit = (element: Element) => {
    if (element.matches(OUTPUT_BOUNDARY)) {
      return;
    }
    classTokens(element).forEach((token) => tokens.add(token));
    Array.from(element.children).forEach(visit);
  };
  visit(root);
  return tokens;
};

const containsIcon = (root: Element): boolean =>
  root.matches("iconify-icon") || root.querySelector("iconify-icon") !== null;

let iconModule: Promise<unknown> | undefined;

const prepareIcons = async (root: Element): Promise<void> => {
  if (!containsIcon(root)) {
    return;
  }
  iconModule ??= import("iconify-icon");
  await iconModule;
};

const defaultGenerator: GenerateViewCss = async (tokens) => {
  const { generateViewCss } = await import("./generator.ts");
  return await generateViewCss(tokens);
};

const mutationTouchesView = (mutation: MutationRecord): boolean => {
  const target =
    mutation.target instanceof Element ? mutation.target : mutation.target.parentElement;
  if (!target) {
    return false;
  }
  if (mutation.type === "attributes") {
    return target.closest(APP_SHELL) !== null && target.closest(OUTPUT_BOUNDARY) === null;
  }
  if (target.closest(OUTPUT_BOUNDARY)) {
    return false;
  }
  if (target.closest(APP_SHELL)) {
    return true;
  }
  return Array.from(mutation.addedNodes).some(
    (node) =>
      node instanceof Element &&
      (node.matches(APP_SHELL) || node.querySelector(APP_SHELL) !== null),
  );
};

const insertRuntimeStyle = (style: HTMLStyleElement): void => {
  const firstPageStyle = document.head.querySelector(
    `link[rel="stylesheet"]:not([${RUNTIME_STYLE}]), style:not([${RUNTIME_STYLE}])`,
  );
  document.head.insertBefore(style, firstPageStyle);
};

export class ViewStyleController {
  private readonly style: HTMLStyleElement;
  private readonly observer: MutationObserver;
  private requestedGeneration = 0;
  private completedGeneration = 0;
  private activeRefresh: Promise<void> | undefined;
  private observed = false;

  constructor(private readonly generate: GenerateViewCss = defaultGenerator) {
    this.style = document.createElement("style");
    this.style.setAttribute(RUNTIME_STYLE, "");
    this.style.setAttribute(VIEW_STYLE, "");
    insertRuntimeStyle(this.style);
    this.observer = new MutationObserver((mutations) => {
      if (mutations.some(mutationTouchesView)) {
        const claim = beginPresentationRefresh("styles");
        void this.refresh()
          .then(() => {
            markStylesReady();
            setPresentationRefreshState(claim, "ready");
          })
          .catch((cause: unknown) => {
            styleFailure(
              "view-styles-failed",
              "View styling could not update. The authored page remains available.",
              "Check the browser console and the view utility classes.",
            );
            setPresentationRefreshState(claim, "error");
            console.error("marimo-studio view styling error", cause);
          });
      }
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (node instanceof Element && node.closest(OUTPUT_BOUNDARY) === null) {
            void prepareIcons(node).catch(() => {
              styleFailure(
                "view-icons-failed",
                "View icons could not start. The authored page remains available.",
                "Check the browser console and the authored icon names.",
              );
            });
          }
        }
      }
    });
  }

  async stage(root: Element): Promise<StagedViewStyles> {
    const css = await this.generate(collectViewClassTokens(root));
    await prepareIcons(root);
    let discarded = false;
    let committed = false;
    const previous = this.style.textContent;
    const requested = this.requestedGeneration;
    const completed = this.completedGeneration;
    const rollback = () => {
      if (!committed) {
        return;
      }
      this.requestedGeneration = requested;
      this.completedGeneration = completed;
      this.style.textContent = previous;
      committed = false;
    };
    return {
      commit: () => {
        if (discarded) {
          return;
        }
        this.requestedGeneration += 1;
        this.completedGeneration = this.requestedGeneration;
        this.style.textContent = css;
        committed = true;
      },
      rollback,
      finalize: () => {
        if (committed && this.observed) {
          this.observer.takeRecords();
        }
      },
      discard: () => {
        rollback();
        discarded = true;
      },
    };
  }

  observe(): void {
    if (this.observed) {
      return;
    }
    this.observer.observe(document.body, {
      attributes: true,
      attributeFilter: ["class"],
      childList: true,
      subtree: true,
    });
    this.observed = true;
  }

  disconnect(): void {
    this.observer.disconnect();
    this.observed = false;
    this.requestedGeneration += 1;
  }

  refresh(): Promise<void> {
    this.requestedGeneration += 1;
    this.activeRefresh ??= this.runRefreshes().finally(() => {
      this.activeRefresh = undefined;
    });
    return this.activeRefresh;
  }

  private async runRefreshes(): Promise<void> {
    while (this.completedGeneration < this.requestedGeneration) {
      const generation = this.requestedGeneration;
      const root = appShell();
      if (!root) {
        this.completedGeneration = generation;
        continue;
      }
      const css = await this.generate(collectViewClassTokens(root));
      await prepareIcons(root);
      if (generation === this.requestedGeneration) {
        this.style.textContent = css;
      }
      this.completedGeneration = generation;
    }
  }
}

const viewStyles = (): ViewStyleController => {
  controller ??= new ViewStyleController();
  return controller;
};

export const stageViewStyles = async (root: Element): Promise<StagedViewStyles> =>
  await viewStyles().stage(root);

export interface ViewStyleDiagnostic {
  code: string;
  message: string;
  hint: string;
}

const styleFailure = (code: string, message: string, hint: string): ViewStyleDiagnostic => {
  currentDiagnostic = { code, message, hint };
  clearTimeout(globalThis.__MARIMO_STUDIO_STYLE_TIMEOUT__);
  document.documentElement.dataset.marimoStudioStyles = "error";
  if (ownedDiagnosticHost?.isConnected) {
    ownedDiagnosticHost.dataset.marimoDiagnosticCode = code;
    ownedDiagnosticHost.dataset.marimoDiagnosticMessage = message;
    ownedDiagnosticHost.dataset.marimoDiagnosticHint = hint;
    ownedDiagnosticHost.dataset.marimoDiagnosticScope = "presentation";
    ownedDiagnosticHost.dataset.state = "error";
    ownedDiagnosticHost.textContent = message;
    return { code, message, hint };
  }
  const status = document.createElement("div");
  status.dataset.marimoStudioStyleError = "";
  status.dataset.marimoDiagnosticCode = code;
  status.dataset.marimoDiagnosticMessage = message;
  status.dataset.marimoDiagnosticHint = hint;
  status.dataset.marimoDiagnosticScope = "presentation";
  status.dataset.state = "error";
  status.setAttribute("role", "alert");
  status.textContent = message;
  document.body.append(status);
  ownedDiagnosticHost = status;
  return { code, message, hint };
};

const markStylesReady = (): void => {
  currentDiagnostic = undefined;
  clearTimeout(globalThis.__MARIMO_STUDIO_STYLE_TIMEOUT__);
  ownedDiagnosticHost?.remove();
  ownedDiagnosticHost = undefined;
  document.documentElement.dataset.marimoStudioStyles = "ready";
};

export interface ViewStyleScopeTarget {
  readonly CSSScopeRule?: abstract new (...arguments_: never[]) => CSSRule;
}

export const viewStyleDiagnostic = (): ViewStyleDiagnostic | undefined => {
  if (currentDiagnostic && !ownedDiagnosticHost?.isConnected) {
    currentDiagnostic = undefined;
  }
  return currentDiagnostic;
};

export const supportsViewStyleScope = (target: ViewStyleScopeTarget = globalThis): boolean =>
  "CSSScopeRule" in target;

export const initializeViewStyles = async (
  scopeSupported = supportsViewStyleScope(),
  signal?: AbortSignal,
): Promise<ViewStyleDiagnostic | undefined> => {
  if (signal?.aborted) {
    throw signal.reason;
  }
  document.documentElement.dataset.marimoStudioStyles = "loading";
  if (!scopeSupported) {
    return styleFailure(
      "view-styles-unsupported",
      "View utilities require a browser with CSS @scope support. Authored CSS and notebook outputs remain available.",
      "Open the view in a browser that supports CSS @scope.",
    );
  }
  try {
    const shell = appShell();
    if (!shell) {
      throw new Error("Missing #app-shell");
    }
    const styles = viewStyles();
    styles.observe();
    await styles.refresh();
    if (signal?.aborted) {
      throw signal.reason;
    }
    markStylesReady();
    return undefined;
  } catch (error) {
    if (signal?.aborted) {
      throw signal.reason;
    }
    const diagnostic = styleFailure(
      "view-styles-failed",
      "View styling could not start. The authored page remains available.",
      "Check the browser console and the view utility classes.",
    );
    console.error("marimo-studio view styling error", error);
    return diagnostic;
  }
};
