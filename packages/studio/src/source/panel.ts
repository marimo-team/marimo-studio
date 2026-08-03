import { sourceNameSchema, type SourceName } from "@marimo-studio/protocol/source-events";

import type { SourceEditorController } from "./editor.tsx";
import type { SourcePhase, SourceState } from "./sync.ts";

export interface SourcePanelActions {
  edit(name: SourceName, content: string): void;
  save(name: SourceName): void;
  activate(name: SourceName): void;
  useDisk(): void;
  keepLocal(): void;
}

const SOURCE_NAMES = sourceNameSchema.options;
const SOURCE_LANGUAGES = {
  "index.html": "html",
  "app.css": "css",
} as const satisfies Record<SourceName, "html" | "css">;
const SOURCE_STATUS = {
  loading: "Loading",
  saving: "Saving…",
  external: "Updated from disk",
  conflict: "Conflict",
  saved: "Saved ✓",
} satisfies Record<Exclude<SourcePhase, "error">, string>;
const SOURCE_TAB_MOVES = new Map<string, (index: number) => number>([
  ["ArrowRight", (index) => (index + 1) % SOURCE_NAMES.length],
  ["ArrowLeft", (index) => (index - 1 + SOURCE_NAMES.length) % SOURCE_NAMES.length],
  ["Home", () => 0],
  ["End", () => SOURCE_NAMES.length - 1],
]);

const sourceTabForKey = (current: SourceName, key: string): SourceName | undefined => {
  const move = SOURCE_TAB_MOVES.get(key);
  const index = SOURCE_NAMES.indexOf(current);
  if (!move || index < 0) {
    return undefined;
  }
  return SOURCE_NAMES[move(index)];
};

const sourceStatus = (state: SourceState): string => {
  if (state.phase === "error") {
    return state.message ?? "Could not save";
  }
  return SOURCE_STATUS[state.phase];
};

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
    const tab = document.querySelector<HTMLElement>(`[data-source-tab="${state.name}"]`);
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
    const { mountSourceEditor } = await import("./editor.tsx");
    for (const name of SOURCE_NAMES) {
      const host = document.querySelector<HTMLElement>(`[data-source-editor="${name}"]`);
      if (!host) {
        throw new Error(`Studio source host ${name} is missing`);
      }
      this.editors.set(
        name,
        mountSourceEditor(host, {
          language: SOURCE_LANGUAGES[name],
          onChange: (content) => {
            if (!this.applying.has(name)) {
              this.actions.edit(name, content);
            }
          },
          onSave: () => this.actions.save(name),
        }),
      );
    }
    document.querySelectorAll<HTMLButtonElement>("[data-source-tab]").forEach((button) => {
      button.addEventListener("click", () => {
        const name = sourceNameSchema.safeParse(button.dataset.sourceTab);
        if (name.success) {
          this.actions.activate(name.data);
        }
      });
      button.addEventListener("keydown", (event) => {
        const current = sourceNameSchema.safeParse(button.dataset.sourceTab);
        if (!current.success) {
          return;
        }
        const next = sourceTabForKey(current.data, event.key);
        if (!next) {
          return;
        }
        event.preventDefault();
        this.actions.activate(next);
        document.querySelector<HTMLElement>(`[data-source-tab="${next}"]`)?.focus();
      });
    });
    document
      .querySelector<HTMLButtonElement>("[data-conflict-compare]")
      ?.addEventListener("click", () => this.toggleCompare());
    document
      .querySelector<HTMLButtonElement>("[data-conflict-disk]")
      ?.addEventListener("click", () => this.actions.useDisk());
    document
      .querySelector<HTMLButtonElement>("[data-conflict-local]")
      ?.addEventListener("click", () => this.actions.keepLocal());
  }

  private renderActive(): void {
    document.querySelectorAll<HTMLButtonElement>("[data-source-tab]").forEach((button) => {
      const selected = button.dataset.sourceTab === this.active;
      button.setAttribute("aria-selected", String(selected));
      button.tabIndex = selected ? 0 : -1;
    });
    document.querySelectorAll<HTMLElement>("[data-source-editor]").forEach((editor) => {
      editor.hidden = editor.dataset.sourceEditor !== this.active;
    });
    const path = document.querySelector<HTMLElement>("[data-source-path]");
    if (path) {
      path.textContent = `${this.view}/${this.active}`;
    }
  }

  private renderState(state: SourceState): void {
    const status = document.querySelector<HTMLElement>("[data-source-status]");
    const conflict = document.querySelector<HTMLElement>("[data-source-conflict]");
    const compare = document.querySelector<HTMLElement>("[data-source-compare]");
    if (!status || !conflict || !compare) {
      return;
    }
    if (this.statusTimer !== undefined) {
      clearTimeout(this.statusTimer);
      this.statusTimer = undefined;
    }
    status.dataset.state = state.phase;
    status.textContent = sourceStatus(state);
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
    const message = conflict.querySelector<HTMLElement>("[data-source-conflict-message]");
    if (message) {
      message.textContent = `${this.active} changed on disk while you were editing.`;
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
    const compare = document.querySelector<HTMLElement>("[data-source-compare]");
    if (compare) {
      compare.hidden = !compare.hidden;
    }
  }
}
