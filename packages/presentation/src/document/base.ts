export const resolveDocumentBase = (source: Document, documentUrl: string): string => {
  const href = source.querySelector("base")?.getAttribute("href") ?? documentUrl;
  return new URL(href, new URL(documentUrl, globalThis.location.href)).href;
};

const setDocumentBase = (href: string, target: Document): void => {
  let base = target.querySelector("base");
  if (!base) {
    base = target.createElement("base");
    target.head.prepend(base);
  }
  base.setAttribute("href", href);
};

export class DocumentBase {
  private href: string;
  private observer: MutationObserver | undefined;

  constructor(private readonly target: Document = document) {
    this.href = target.baseURI;
  }

  start(href = this.href): void {
    this.set(href);
    if (this.observer) {
      return;
    }
    this.observer = new MutationObserver(() => this.restore());
    this.observer.observe(this.target.head, {
      attributes: true,
      attributeFilter: ["href"],
      childList: true,
      subtree: true,
    });
  }

  set(href: string): void {
    this.href = new URL(href, globalThis.location.href).href;
    this.restore();
  }

  stop(): void {
    this.observer?.disconnect();
    this.observer = undefined;
  }

  private restore(): void {
    if (this.target.baseURI !== this.href) {
      setDocumentBase(this.href, this.target);
    }
  }
}

export const documentBase = new DocumentBase();
