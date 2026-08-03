import { css } from "@codemirror/lang-css";
import { html } from "@codemirror/lang-html";
import ReactCodeMirror, { EditorView, type ReactCodeMirrorRef } from "@uiw/react-codemirror";
import { createElement } from "react";
import { createRoot } from "react-dom/client";

export interface SourceEditorController {
  setValue(value: string): void;
  focus(): void;
  requestMeasure(): void;
  destroy(): void;
}

interface SourceEditorOptions {
  language: "html" | "css";
  onChange(value: string): void;
  onSave(): void;
}

export const mountSourceEditor = (
  host: HTMLElement,
  options: SourceEditorOptions,
): SourceEditorController => {
  const root = createRoot(host);
  const reference: ReactCodeMirrorRef = {};
  const colorScheme = globalThis.matchMedia("(prefers-color-scheme: dark)");
  let value = "";

  const render = () => {
    const language = options.language === "html" ? html() : css();
    const label = options.language === "html" ? "HTML source" : "CSS source";
    root.render(
      createElement(ReactCodeMirror, {
        ref: (next: ReactCodeMirrorRef | null) => {
          if (next) {
            Object.assign(reference, next);
          }
        },
        value,
        height: "100%",
        width: "100%",
        theme: colorScheme.matches ? "dark" : "light",
        extensions: [language, EditorView.contentAttributes.of({ "aria-label": label })],
        basicSetup: {
          autocompletion: true,
          bracketMatching: true,
          closeBrackets: true,
          foldGutter: true,
          highlightActiveLine: true,
          highlightActiveLineGutter: true,
          highlightSelectionMatches: true,
          history: true,
          lineNumbers: true,
          searchKeymap: true,
        },
        onChange: (next) => {
          value = next;
          options.onChange(next);
        },
      }),
    );
  };

  const save = (event: KeyboardEvent) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      options.onSave();
    }
  };
  const refreshTheme = () => render();
  host.addEventListener("keydown", save);
  colorScheme.addEventListener("change", refreshTheme);
  render();

  return {
    setValue(next) {
      const current = reference.view?.state.doc.toString() ?? value;
      value = next;
      if (current === next) {
        return;
      }
      render();
    },
    focus() {
      reference.view?.focus();
    },
    requestMeasure() {
      reference.view?.requestMeasure();
    },
    destroy() {
      host.removeEventListener("keydown", save);
      colorScheme.removeEventListener("change", refreshTheme);
      root.unmount();
    },
  };
};
