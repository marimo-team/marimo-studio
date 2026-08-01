import { notifyPageTheme } from "./page-theme.ts";

const PAGE_STYLE_ATTRIBUTE = "data-marimo-studio-page-style";
const STAGED_STYLE_ATTRIBUTE = "data-marimo-studio-staged-style";
const PAGE_STYLE_SELECTOR = `link[rel="stylesheet"][${PAGE_STYLE_ATTRIBUTE}]` +
  `:not([${STAGED_STYLE_ATTRIBUTE}]), ` +
  `style[${PAGE_STYLE_ATTRIBUTE}]:not([${STAGED_STYLE_ATTRIBUTE}])`;
const STYLESHEET_LOAD_TIMEOUT_MS = 10_000;

export interface StagedStyles {
  commit(): void;
  discard(): void;
}

export const abortError = () =>
  new DOMException("Refresh superseded", "AbortError");

export const isAbortError = (error: unknown): boolean =>
  error instanceof DOMException && error.name === "AbortError";

export class StylesheetRefreshError extends Error {
  constructor(
    message: string,
    readonly code:
      | "stylesheet-refresh-failed"
      | "stylesheet-refresh-timeout",
  ) {
    super(message);
    this.name = "StylesheetRefreshError";
  }
}

export class PageStyles {
  private active: AbortController | undefined;

  mark(root: ParentNode): void {
    root.querySelectorAll<HTMLElement>(
      'head > link[rel="stylesheet"]:not([data-marimo-studio-runtime]), ' +
        "head > style:not([data-marimo-studio-runtime])",
    ).forEach((element) => element.setAttribute(PAGE_STYLE_ATTRIBUTE, ""));
  }

  abort(): void {
    this.active?.abort();
  }

  async refresh(documentUrl: string): Promise<void> {
    this.abort();
    const controller = new AbortController();
    this.active = controller;
    let staged: StagedStyles | undefined;
    try {
      staged = await this.stage(document, documentUrl, controller.signal);
      if (controller.signal.aborted || this.active !== controller) {
        throw abortError();
      }
      staged.commit();
      staged = undefined;
    } finally {
      staged?.discard();
      if (this.active === controller) {
        this.active = undefined;
      }
    }
  }

  async stage(
    nextDocument: Document,
    documentUrl: string,
    signal: AbortSignal,
  ): Promise<StagedStyles> {
    const current = Array.from(
      document.querySelectorAll<HTMLElement>(PAGE_STYLE_SELECTOR),
    );
    const staged = Array.from(
      nextDocument.querySelectorAll<HTMLElement>(PAGE_STYLE_SELECTOR),
      (element) => {
        const clone = element.cloneNode(true) as HTMLElement;
        const media = clone.getAttribute("media");
        clone.setAttribute("media", "not all");
        clone.setAttribute(STAGED_STYLE_ATTRIBUTE, "");
        if (clone instanceof HTMLLinkElement) {
          clone.href = stylesheetUrl(clone, nextDocument, documentUrl);
        }
        return { clone, media };
      },
    );
    const discard = () => staged.forEach(({ clone }) => clone.remove());
    if (signal.aborted) {
      throw abortError();
    }
    const loads: Promise<void>[] = [];
    staged.forEach(({ clone }) => {
      if (clone instanceof HTMLLinkElement) {
        loads.push(waitForStylesheet(clone, signal));
      }
      document.head.append(clone);
    });
    try {
      await Promise.all(loads);
      if (signal.aborted) {
        throw abortError();
      }
    } catch (error) {
      discard();
      throw error;
    }
    return {
      commit: () => {
        current.forEach((element) => element.remove());
        staged.forEach(({ clone, media }) => {
          clone.removeAttribute(STAGED_STYLE_ATTRIBUTE);
          if (media === null) {
            clone.removeAttribute("media");
          } else {
            clone.setAttribute("media", media);
          }
        });
        notifyPageTheme();
      },
      discard,
    };
  }
}

const stylesheetUrl = (
  link: HTMLLinkElement,
  nextDocument: Document,
  documentUrl: string,
): string => {
  const base = nextDocument.querySelector("base")?.getAttribute("href");
  const baseUrl = base
    ? new URL(base, new URL(documentUrl, globalThis.location.href)).toString()
    : new URL(documentUrl, globalThis.location.href).toString();
  const url = new URL(link.getAttribute("href") ?? link.href, baseUrl);
  url.searchParams.set("_marimo_studio_reload", Date.now().toString());
  return url.toString();
};

const waitForStylesheet = (
  link: HTMLLinkElement,
  signal: AbortSignal,
): Promise<void> =>
  new Promise((resolve, reject) => {
    const settle = (result: () => void) => {
      clearTimeout(timeout);
      link.removeEventListener("load", loaded);
      link.removeEventListener("error", failed);
      signal.removeEventListener("abort", aborted);
      result();
    };
    const loaded = () => settle(resolve);
    const failed = () =>
      settle(() =>
        reject(
          new StylesheetRefreshError(
            `Stylesheet failed to load: ${link.href}`,
            "stylesheet-refresh-failed",
          ),
        )
      );
    const aborted = () => settle(() => reject(abortError()));
    const timeout = setTimeout(
      () =>
        settle(() =>
          reject(
            new StylesheetRefreshError(
              `Stylesheet did not finish loading: ${link.href}`,
              "stylesheet-refresh-timeout",
            ),
          )
        ),
      STYLESHEET_LOAD_TIMEOUT_MS,
    );
    link.addEventListener("load", loaded);
    link.addEventListener("error", failed);
    signal.addEventListener("abort", aborted, { once: true });
  });
