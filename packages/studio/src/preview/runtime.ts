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

  constructor(
    initial: string,
    private readonly storageKey: string,
    private readonly select: (runtime: string) => void,
  ) {
    this.current = initial;
    this.buttons = Array.from(
      document.querySelectorAll<HTMLButtonElement>("[data-preview-runtime]"),
    );
    this.buttons.forEach((button) => button.addEventListener("click", this.clicked));
    this.render();
  }

  dispose(): void {
    this.buttons.forEach((button) => button.removeEventListener("click", this.clicked));
  }

  private readonly clicked = (event: MouseEvent): void => {
    const runtime = (event.currentTarget as HTMLButtonElement).dataset.previewRuntime;
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
      button.setAttribute("aria-pressed", String(button.dataset.previewRuntime === this.current));
    });
  }
}
