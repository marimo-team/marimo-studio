import { css } from "@codemirror/lang-css";
import { html } from "@codemirror/lang-html";
import ReactCodeMirror, { EditorView, type ReactCodeMirrorRef } from "@uiw/react-codemirror";
import {
  forwardRef,
  type KeyboardEvent as ReactKeyboardEvent,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
} from "react";

import { useStudioTheme } from "../../shared/theme.tsx";

export interface SourceEditorHandle {
  focus(): void;
  requestMeasure(): void;
}

interface SourceEditorProps {
  active: boolean;
  language: "html" | "css";
  value: string;
  onChange: (value: string) => void;
  onSave: () => void;
}

const basicSetup = {
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
} as const;

const LANGUAGE_CONFIG = {
  css: { extension: css, label: "CSS source" },
  html: { extension: html, label: "HTML source" },
} as const;

export const SourceEditor = forwardRef<SourceEditorHandle, SourceEditorProps>(function SourceEditor(
  { active, language, value, onChange, onSave },
  forwardedRef,
) {
  const editor = useRef<ReactCodeMirrorRef>({});
  const theme = useStudioTheme();
  const extensions = useMemo(() => {
    const config = LANGUAGE_CONFIG[language];
    return [config.extension(), EditorView.contentAttributes.of({ "aria-label": config.label })];
  }, [language]);

  useImperativeHandle(
    forwardedRef,
    () => ({
      focus: () => editor.current.view?.focus(),
      requestMeasure: () => editor.current.view?.requestMeasure(),
    }),
    [],
  );

  useEffect(() => {
    if (active) {
      editor.current.view?.requestMeasure();
    }
  }, [active]);

  const save = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      onSave();
    }
  };

  return (
    <div className="studio-source-editor-root" onKeyDownCapture={save}>
      <ReactCodeMirror
        ref={editor}
        value={value}
        height="100%"
        width="100%"
        theme={theme}
        extensions={extensions}
        basicSetup={basicSetup}
        onChange={onChange}
      />
    </div>
  );
});
