export const previewRuntimeStorageKey = (workspaceId: string): string =>
  `marimo-studio:preview-runtime:v1:${workspaceId}`;

export const initialPreviewRuntime = ({
  available,
  configured,
  stored,
}: {
  available: readonly string[];
  configured: string;
  stored: string | null;
}): string => {
  if (stored && available.includes(stored)) {
    return stored;
  }
  if (available.includes(configured)) {
    return configured;
  }
  const fallback = available[0];
  if (!fallback) {
    throw new Error("Studio requires at least one preview runtime");
  }
  return fallback;
};

export class RuntimeControl {
  private current: string;
  private readonly buttons: HTMLButtonElement[];
  private readonly label: HTMLElement;
  private readonly trigger: HTMLElement;

  constructor(
    root: ParentNode,
    initial: string,
    private readonly storageKey: string,
    private readonly select: (runtime: string) => void,
  ) {
    this.current = initial;
    this.buttons = Array.from(root.querySelectorAll<HTMLButtonElement>("[data-preview-runtime]"));
    const label = root.querySelector<HTMLElement>("[data-preview-runtime-label]");
    const trigger = root.querySelector<HTMLElement>("[data-runtime-trigger]");
    if (!label || !trigger) {
      throw new Error("Studio runtime controls are incomplete");
    }
    this.label = label;
    this.trigger = trigger;
    this.buttons.forEach((button) => button.addEventListener("click", this.clicked));
    this.render();
  }

  dispose(): void {
    this.buttons.forEach((button) => button.removeEventListener("click", this.clicked));
  }

  private readonly clicked = (event: MouseEvent): void => {
    const button = event.currentTarget as HTMLButtonElement;
    button.closest("details")?.removeAttribute("open");
    const runtime = button.dataset.previewRuntime;
    if (!runtime || runtime === this.current) {
      return;
    }
    this.current = runtime;
    globalThis.localStorage.setItem(this.storageKey, runtime);
    this.render();
    this.select(runtime);
  };

  private render(): void {
    this.buttons.forEach((button) => {
      const selected = button.dataset.previewRuntime === this.current;
      button.setAttribute("aria-pressed", String(selected));
      if (selected) {
        this.label.textContent = button.querySelector("strong")?.textContent ?? this.current;
        this.trigger.setAttribute("aria-label", `${this.label.textContent} preview runtime`);
      }
    });
  }
}
