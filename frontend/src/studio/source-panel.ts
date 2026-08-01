import type { SourceEditorController } from "../marimo-adapter/source-editor.tsx";
import type { SourceName } from "./source-remote.ts";
import type { SourceState } from "./source-sync.ts";

export interface SourcePanelActions {
  edit(name: SourceName, content: string): void;
  save(name: SourceName): void;
  activate(name: SourceName): void;
  useDisk(): void;
  keepLocal(): void;
}

const SOURCE_NAMES: readonly SourceName[] = ["index.html", "app.css"];

export class SourcePanel {
  private readonly editors = new Map<SourceName, SourceEditorController>();
  private readonly applying = new Set<SourceName>();
  private statusTimer: ReturnType<typeof setTimeout> | undefined;
  private active: SourceName;
  private view: string;

  private constructor(
    initialView: string,
    initialActive: SourceName,
    private readonly actions: SourcePanelActions,
  ) {
    this.view = initialView;
    this.active = initialActive;
  }

  static async create(
    initialView: string,
    initialActive: SourceName,
    actions: SourcePanelActions,
  ): Promise<SourcePanel> {
    const panel = new SourcePanel(initialView, initialActive, actions);
    await panel.mount();
    panel.renderActive();
    return panel;
  }

  setView(view: string, active: SourceName): void {
    this.view = view;
    this.active = active;
    this.renderActive();
  }

  activate(name: SourceName): void {
    this.active = name;
    this.renderActive();
    this.editors.get(name)?.requestMeasure();
  }

  document(name: SourceName, content: string): void {
    const editor = this.editors.get(name);
    if (!editor) {
      return;
    }
    this.applying.add(name);
    editor.setValue(content);
    queueMicrotask(() => this.applying.delete(name));
  }

  state(state: SourceState): void {
    const tab = document.querySelector<HTMLElement>(
      `[data-source-tab="${state.name}"]`,
    );
    if (tab) {
      tab.dataset.state = state.phase;
    }
    if (state.name === this.active) {
      this.renderState(state);
    }
  }

  focusHtml(): void {
    this.activate("index.html");
    globalThis.setTimeout(() => this.editors.get("index.html")?.focus(), 0);
  }

  requestMeasure(): void {
    this.editors.forEach((editor) => editor.requestMeasure());
  }

  dispose(): void {
    this.editors.forEach((editor) => editor.destroy());
    if (this.statusTimer !== undefined) {
      clearTimeout(this.statusTimer);
    }
  }

  private async mount(): Promise<void> {
    const { mountSourceEditor } = await import(
      "../marimo-adapter/source-editor.tsx"
    );
    for (const name of SOURCE_NAMES) {
      const host = document.querySelector<HTMLElement>(
        `[data-source-editor="${name}"]`,
      );
      if (!host) {
        throw new Error(`Studio source host ${name} is missing`);
      }
      this.editors.set(
        name,
        mountSourceEditor(host, {
          language: name === "index.html" ? "html" : "css",
          onChange: (content) => {
            if (!this.applying.has(name)) {
              this.actions.edit(name, content);
            }
          },
          onSave: () => this.actions.save(name),
        }),
      );
    }
    document.querySelectorAll<HTMLButtonElement>("[data-source-tab]").forEach(
      (button) => {
        button.addEventListener("click", () => {
          const name = button.dataset.sourceTab;
          if (name === "index.html" || name === "app.css") {
            this.actions.activate(name);
          }
        });
        button.addEventListener("keydown", (event) => {
          const current = button.dataset.sourceTab as SourceName;
          const index = SOURCE_NAMES.indexOf(current);
          const next = event.key === "ArrowRight"
            ? SOURCE_NAMES[(index + 1) % SOURCE_NAMES.length]
            : event.key === "ArrowLeft"
            ? SOURCE_NAMES[
              (index - 1 + SOURCE_NAMES.length) %
              SOURCE_NAMES.length
            ]
            : event.key === "Home"
            ? SOURCE_NAMES[0]
            : event.key === "End"
            ? SOURCE_NAMES.at(-1)!
            : undefined;
          if (!next) {
            return;
          }
          event.preventDefault();
          this.actions.activate(next);
          document.querySelector<HTMLElement>(
            `[data-source-tab="${next}"]`,
          )?.focus();
        });
      },
    );
    document.querySelector<HTMLButtonElement>("[data-conflict-compare]")
      ?.addEventListener("click", () => this.toggleCompare());
    document.querySelector<HTMLButtonElement>("[data-conflict-disk]")
      ?.addEventListener("click", () => this.actions.useDisk());
    document.querySelector<HTMLButtonElement>("[data-conflict-local]")
      ?.addEventListener("click", () => this.actions.keepLocal());
  }

  private renderActive(): void {
    document.querySelectorAll<HTMLButtonElement>("[data-source-tab]").forEach(
      (button) => {
        const selected = button.dataset.sourceTab === this.active;
        button.setAttribute("aria-selected", String(selected));
        button.tabIndex = selected ? 0 : -1;
      },
    );
    document.querySelectorAll<HTMLElement>("[data-source-editor]").forEach(
      (editor) => {
        editor.hidden = editor.dataset.sourceEditor !== this.active;
      },
    );
    const path = document.querySelector<HTMLElement>("[data-source-path]");
    if (path) {
      path.textContent = `${this.view}/${this.active}`;
    }
  }

  private renderState(state: SourceState): void {
    const status = document.querySelector<HTMLElement>("[data-source-status]");
    const conflict = document.querySelector<HTMLElement>(
      "[data-source-conflict]",
    );
    const compare = document.querySelector<HTMLElement>(
      "[data-source-compare]",
    );
    if (!status || !conflict || !compare) {
      return;
    }
    if (this.statusTimer !== undefined) {
      clearTimeout(this.statusTimer);
      this.statusTimer = undefined;
    }
    status.dataset.state = state.phase;
    status.textContent = state.phase === "loading"
      ? "Loading"
      : state.phase === "saving"
      ? "Saving…"
      : state.phase === "external"
      ? "Updated from disk"
      : state.phase === "conflict"
      ? "Conflict"
      : state.phase === "error"
      ? state.message ?? "Could not save"
      : "Saved ✓";
    if (state.phase === "external") {
      this.statusTimer = setTimeout(() => {
        status.dataset.state = "saved";
        status.textContent = "Saved ✓";
      }, 1800);
    }
    const sourceConflict = state.conflict;
    conflict.hidden = sourceConflict === undefined;
    if (!sourceConflict) {
      compare.hidden = true;
      return;
    }
    const message = conflict.querySelector<HTMLElement>(
      "[data-source-conflict-message]",
    );
    if (message) {
      message.textContent =
        `${this.active} changed on disk while you were editing.`;
    }
    const local = compare.querySelector<HTMLElement>("[data-compare-local]");
    const disk = compare.querySelector<HTMLElement>("[data-compare-disk]");
    if (local) {
      local.textContent = sourceConflict.local;
    }
    if (disk) {
      disk.textContent = sourceConflict.remote.content;
    }
  }

  private toggleCompare(): void {
    const compare = document.querySelector<HTMLElement>(
      "[data-source-compare]",
    );
    if (compare) {
      compare.hidden = !compare.hidden;
    }
  }
}
