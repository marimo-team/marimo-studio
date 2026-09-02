import {
  Annotation,
  Compartment,
  EditorSelection,
  EditorState,
  Transaction,
  type Extension,
} from "@codemirror/state";
import { EditorView, getDefaultExtensions, type ViewUpdate } from "@uiw/react-codemirror";
import {
  forwardRef,
  type KeyboardEvent as ReactKeyboardEvent,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { useStudioTheme } from "../../shared/theme.tsx";
import { loadSourceLanguage, plainTextSourceLanguage } from "./languages.ts";

export interface SourceEditorHandle {
  focus(): void;
  requestMeasure(): void;
}

interface SourceEditorProps {
  active: boolean;
  documentId: string;
  incarnation: number;
  label: string;
  language: string;
  readOnly: boolean;
  replacementVersion: number;
  value: string;
  onChange: (value: string) => void;
  onSave: () => void;
}

interface StoredEditorState {
  replacementVersion: number;
  state: EditorState;
  scrollTop: number;
  scrollLeft: number;
}

interface EditorCompartments {
  access: Compartment;
  attributes: Compartment;
  language: Compartment;
  theme: Compartment;
}

const externalChange = Annotation.define<boolean>();

const sourceLineSeparator = (value: string): string | undefined => {
  const separators = value.match(/\r\n|\r|\n/g);
  const first = separators?.[0];
  return first !== undefined && separators?.every((separator) => separator === first) === true
    ? first
    : undefined;
};

const sourceEditorState = (value: string, extensions: readonly Extension[]): EditorState => {
  const lineSeparator = sourceLineSeparator(value);
  return EditorState.create({
    doc: value,
    extensions:
      lineSeparator === undefined
        ? extensions
        : [...extensions, EditorState.lineSeparator.of(lineSeparator)],
  });
};

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

const synchronizeValue = (view: EditorView, value: string): void => {
  if (view.state.sliceDoc() === value) {
    return;
  }
  view.dispatch({
    changes: { from: 0, to: view.state.doc.length, insert: value },
    annotations: [externalChange.of(true), Transaction.addToHistory.of(false)],
  });
};

const editorStateKey = (documentId: string, incarnation: number): string =>
  `${documentId}\u0000${incarnation}`;

const replacementState = (
  view: EditorView,
  value: string,
  extensions: readonly Extension[],
): EditorState => {
  const state = sourceEditorState(value, extensions);
  const length = state.doc.length;
  const ranges = view.state.selection.ranges.map((range) =>
    EditorSelection.range(Math.min(range.anchor, length), Math.min(range.head, length)),
  );
  return state.update({
    selection: EditorSelection.create(ranges, view.state.selection.mainIndex),
    annotations: Transaction.addToHistory.of(false),
  }).state;
};

export const SourceEditor = forwardRef<SourceEditorHandle, SourceEditorProps>(function SourceEditor(
  {
    active,
    documentId,
    incarnation,
    label,
    language,
    readOnly,
    replacementVersion,
    value,
    onChange,
    onSave,
  },
  forwardedRef,
) {
  const container = useRef<HTMLDivElement | null>(null);
  const editor = useRef<EditorView | null>(null);
  const states = useRef(new Map<string, StoredEditorState>());
  const incarnations = useRef(new Map<string, string>());
  const [compartments] = useState<EditorCompartments>(() => ({
    access: new Compartment(),
    attributes: new Compartment(),
    language: new Compartment(),
    theme: new Compartment(),
  }));
  const [initialStateKey] = useState(() => editorStateKey(documentId, incarnation));
  const currentDocument = useRef(initialStateKey);
  const scrollFrame = useRef<number | undefined>(undefined);
  const onChangeRef = useRef(onChange);
  const theme = useStudioTheme();
  const [loadedLanguage, setLoadedLanguage] = useState<{
    id: string;
    extension: Extension;
  }>({ id: "", extension: plainTextSourceLanguage() });
  const languageExtension =
    loadedLanguage.id === language ? loadedLanguage.extension : plainTextSourceLanguage();
  const updateListener = useMemo(
    () =>
      EditorView.updateListener.of((update: ViewUpdate) => {
        const document = currentDocument.current;
        const stored = states.current.get(document);
        states.current.set(document, {
          replacementVersion: stored?.replacementVersion ?? 0,
          state: update.state,
          scrollTop: stored?.scrollTop ?? 0,
          scrollLeft: stored?.scrollLeft ?? 0,
        });
        if (
          update.docChanged &&
          !update.transactions.some((transaction) => transaction.annotation(externalChange))
        ) {
          onChangeRef.current(update.state.sliceDoc());
        }
      }),
    [],
  );
  const baseExtensions = useMemo(
    () => [
      updateListener,
      ...getDefaultExtensions({
        basicSetup,
        theme: "none",
      }),
    ],
    [updateListener],
  );
  const accessExtensions = useMemo(
    () => [EditorView.editable.of(!readOnly), EditorState.readOnly.of(readOnly)],
    [readOnly],
  );
  const attributeExtension = useMemo(
    () =>
      EditorView.contentAttributes.of({
        "aria-label": label,
        "aria-readonly": String(readOnly),
        tabindex: "0",
      }),
    [label, readOnly],
  );
  const themeExtensions = useMemo(
    () =>
      getDefaultExtensions({
        basicSetup: false,
        indentWithTab: false,
        theme,
      }),
    [theme],
  );
  const extensions = useMemo(
    () => [
      ...baseExtensions,
      compartments.access.of(accessExtensions),
      compartments.attributes.of(attributeExtension),
      compartments.language.of(languageExtension),
      compartments.theme.of(themeExtensions),
    ],
    [
      accessExtensions,
      attributeExtension,
      baseExtensions,
      compartments,
      languageExtension,
      themeExtensions,
    ],
  );
  const [initialEditor] = useState(() => ({
    documentId,
    extensions,
    replacementVersion,
    value,
  }));
  useEffect(() => {
    let current = true;
    void loadSourceLanguage(language).then((extension) => {
      if (current) {
        setLoadedLanguage({ id: language, extension });
      }
    });
    return () => {
      current = false;
    };
  }, [language]);

  useLayoutEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  useLayoutEffect(() => {
    const parent = container.current;
    if (!parent) {
      return;
    }
    const state = sourceEditorState(initialEditor.value, initialEditor.extensions);
    const view = new EditorView({ parent, state });
    editor.current = view;
    const key = currentDocument.current;
    incarnations.current.set(initialEditor.documentId, key);
    states.current.set(key, {
      replacementVersion: initialEditor.replacementVersion,
      state,
      scrollTop: 0,
      scrollLeft: 0,
    });
    return () => {
      if (scrollFrame.current !== undefined) {
        globalThis.cancelAnimationFrame(scrollFrame.current);
      }
      view.destroy();
      editor.current = null;
    };
  }, [initialEditor]);

  useLayoutEffect(() => {
    const view = editor.current;
    if (!view) {
      return;
    }
    const key = editorStateKey(documentId, incarnation);
    const previousIncarnation = incarnations.current.get(documentId);
    if (previousIncarnation !== undefined && previousIncarnation !== key) {
      states.current.delete(previousIncarnation);
    }
    incarnations.current.set(documentId, key);
    let restored: StoredEditorState | undefined;
    if (currentDocument.current !== key) {
      if (scrollFrame.current !== undefined) {
        globalThis.cancelAnimationFrame(scrollFrame.current);
        scrollFrame.current = undefined;
      }
      const outgoing = currentDocument.current;
      const outgoingState = states.current.get(outgoing);
      states.current.set(outgoing, {
        replacementVersion: outgoingState?.replacementVersion ?? 0,
        state: view.state,
        scrollTop: view.scrollDOM.scrollTop,
        scrollLeft: view.scrollDOM.scrollLeft,
      });
      restored = states.current.get(key);
      currentDocument.current = key;
      view.setState(restored?.state ?? sourceEditorState(value, extensions));
    }
    view.dispatch({
      effects: [
        compartments.access.reconfigure(accessExtensions),
        compartments.attributes.reconfigure(attributeExtension),
        compartments.language.reconfigure(languageExtension),
        compartments.theme.reconfigure(themeExtensions),
      ],
    });
    const previous = states.current.get(key);
    const authoritativeReplacement =
      previous !== undefined &&
      previous.replacementVersion !== replacementVersion &&
      view.state.sliceDoc() !== value;
    const preservedScroll = {
      top: restored?.scrollTop ?? view.scrollDOM.scrollTop,
      left: restored?.scrollLeft ?? view.scrollDOM.scrollLeft,
    };
    if (authoritativeReplacement) {
      view.setState(replacementState(view, value, extensions));
    } else {
      synchronizeValue(view, value);
    }
    states.current.set(key, {
      replacementVersion,
      state: view.state,
      scrollTop: preservedScroll.top,
      scrollLeft: preservedScroll.left,
    });
    if (restored || authoritativeReplacement) {
      const restoreScroll = () => {
        view.scrollDOM.scrollTop = preservedScroll.top;
        view.scrollDOM.scrollLeft = preservedScroll.left;
      };
      restoreScroll();
      if (scrollFrame.current !== undefined) {
        globalThis.cancelAnimationFrame(scrollFrame.current);
      }
      scrollFrame.current = globalThis.requestAnimationFrame(() => {
        restoreScroll();
        scrollFrame.current = undefined;
      });
    }
  }, [
    accessExtensions,
    attributeExtension,
    compartments,
    documentId,
    extensions,
    incarnation,
    languageExtension,
    replacementVersion,
    themeExtensions,
    value,
  ]);

  useImperativeHandle(
    forwardedRef,
    () => ({
      focus: () => editor.current?.focus(),
      requestMeasure: () => editor.current?.requestMeasure(),
    }),
    [],
  );

  useEffect(() => {
    if (active) {
      editor.current?.requestMeasure();
    }
  }, [active, documentId]);

  const save = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (!readOnly && (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      onSave();
    }
  };

  return <div ref={container} className="studio-source-editor-root" onKeyDownCapture={save} />;
});
