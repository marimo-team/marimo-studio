const APP_SHELL = "#app-shell";
const AUTHORED_TARGET = "data-marimo-studio-authored";
const OUTPUT_BOUNDARY = "[data-marimo-cell-output]";
const RUNTIME_STYLE = "data-marimo-studio-runtime";
const VIEW_STYLE = "data-marimo-studio-view-utilities";

export interface StagedViewStyles {
  commit(): void;
  discard(): void;
}

type GenerateViewCss = (tokens: ReadonlySet<string>) => Promise<string>;

let controller: ViewStyleController | undefined;

const appShell = (): HTMLElement | undefined =>
  document.querySelector<HTMLElement>(APP_SHELL) ?? undefined;

const classTokens = (element: Element): string[] => Array.from(element.classList).filter(Boolean);

const viewClassTokens = (root: Element, markTargets: boolean): Set<string> => {
  const tokens = new Set<string>();
  const visit = (element: Element) => {
    if (element.matches(OUTPUT_BOUNDARY)) {
      return;
    }
    if (markTargets) {
      element.setAttribute(AUTHORED_TARGET, "");
    }
    classTokens(element).forEach((token) => tokens.add(token));
    Array.from(element.children).forEach(visit);
  };
  visit(root);
  return tokens;
};

export const collectViewClassTokens = (root: Element): Set<string> => viewClassTokens(root, false);

const prepareViewClassTokens = (root: Element): Set<string> => viewClassTokens(root, true);

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
  private generation = 0;
  private observed = false;

  constructor(private readonly generate: GenerateViewCss = defaultGenerator) {
    this.style = document.createElement("style");
    this.style.setAttribute(RUNTIME_STYLE, "");
    this.style.setAttribute(VIEW_STYLE, "");
    insertRuntimeStyle(this.style);
    this.observer = new MutationObserver((mutations) => {
      if (mutations.some(mutationTouchesView)) {
        void this.refresh();
      }
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (node instanceof Element && node.closest(OUTPUT_BOUNDARY) === null) {
            void prepareIcons(node).catch(() => {
              styleFailure("View icons could not start. The authored page remains available.");
            });
          }
        }
      }
    });
  }

  async stage(root: Element): Promise<StagedViewStyles> {
    const css = await this.generate(prepareViewClassTokens(root));
    await prepareIcons(root);
    let discarded = false;
    return {
      commit: () => {
        if (discarded) {
          return;
        }
        this.generation += 1;
        this.style.textContent = css;
      },
      discard: () => {
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
    this.generation += 1;
  }

  private async refresh(): Promise<void> {
    const root = appShell();
    if (!root) {
      return;
    }
    const generation = ++this.generation;
    const css = await this.generate(prepareViewClassTokens(root));
    if (generation === this.generation) {
      this.style.textContent = css;
    }
  }
}

const viewStyles = (): ViewStyleController => {
  controller ??= new ViewStyleController();
  return controller;
};

export const stageViewStyles = async (root: Element): Promise<StagedViewStyles> =>
  await viewStyles().stage(root);

const styleFailure = (message: string): void => {
  const browser = globalThis as typeof globalThis & {
    __MARIMO_STUDIO_STYLE_TIMEOUT__?: ReturnType<typeof setTimeout>;
  };
  clearTimeout(browser.__MARIMO_STUDIO_STYLE_TIMEOUT__);
  document.documentElement.dataset.marimoStudioStyles = "error";
  if (document.querySelector("[data-marimo-studio-style-error]")) {
    return;
  }
  const status = document.createElement("div");
  status.dataset.marimoStudioRuntimeDiagnostic = "";
  status.dataset.marimoStudioStyleError = "";
  status.dataset.state = "error";
  status.setAttribute("role", "alert");
  status.textContent = message;
  document.body.append(status);
};

export const initializeViewStyles = async (): Promise<void> => {
  document.documentElement.dataset.marimoStudioStyles = "loading";
  try {
    const shell = appShell();
    if (!shell) {
      throw new Error("Missing #app-shell");
    }
    const staged = await stageViewStyles(shell);
    staged.commit();
    viewStyles().observe();
    const browser = globalThis as typeof globalThis & {
      __MARIMO_STUDIO_STYLE_TIMEOUT__?: ReturnType<typeof setTimeout>;
    };
    clearTimeout(browser.__MARIMO_STUDIO_STYLE_TIMEOUT__);
    document.querySelector("[data-marimo-studio-style-error]")?.remove();
    document.documentElement.dataset.marimoStudioStyles = "ready";
  } catch (error) {
    styleFailure("View styling could not start. The authored page remains available.");
    throw error;
  }
};
