export type MarimoTheme = "light" | "dark";

export type MarimoThemeListener = (theme: MarimoTheme | undefined) => void;

const readTheme = (body: HTMLElement): MarimoTheme | undefined => {
  // Marimo's ThemeProvider publishes the resolved system theme on the body.
  const theme = body.dataset.theme;
  return theme === "light" || theme === "dark" ? theme : undefined;
};

export const connectMarimoThemeFrame = (
  frame: HTMLIFrameElement,
  listener: MarimoThemeListener,
): (() => void) => {
  let observer: MutationObserver | undefined;
  let current: MarimoTheme | undefined;

  const publish = (body: HTMLElement) => {
    const next = readTheme(body);
    if (next !== current) {
      current = next;
      listener(next);
    }
  };

  const connect = () => {
    observer?.disconnect();
    observer = undefined;
    current = undefined;
    listener(undefined);

    const browser = frame.contentWindow;
    const body = browser?.document.body;
    if (!browser || !body) {
      return;
    }

    publish(body);
    const nextObserver = new MutationObserver(() => publish(body));
    nextObserver.observe(body, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    observer = nextObserver;
  };

  frame.addEventListener("load", connect);
  connect();

  return () => {
    frame.removeEventListener("load", connect);
    observer?.disconnect();
  };
};
