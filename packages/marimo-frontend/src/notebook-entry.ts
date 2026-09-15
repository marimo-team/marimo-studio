/** Attach installed-extension controls to an untitled native editor. */
export const connectNotebookEntry = (
  mount: (target: HTMLElement, save: () => void) => () => void,
): (() => void) => {
  let release: (() => void) | undefined;
  let closed = false;
  const connect = () => {
    const chrome = document.querySelector<HTMLElement>('[data-testid="chrome-wrapper"]');
    const save = document.querySelector<HTMLButtonElement>('[data-testid="save-button"]');
    if (closed || !chrome || !save || release) return;
    const target = document.createElement("div");
    target.id = "marimo-studio-entry";
    document.body.append(target);
    const previousTop = chrome.style.top;
    chrome.style.top = "34px";
    const unmount = mount(target, () =>
      document.querySelector<HTMLButtonElement>('[data-testid="save-button"]')?.click(),
    );
    release = () => {
      unmount();
      target.remove();
      chrome.style.top = previousTop;
    };
  };
  const observer = new MutationObserver(connect);
  observer.observe(document.body, { childList: true, subtree: true });
  connect();
  return () => {
    if (closed) return;
    closed = true;
    observer.disconnect();
    release?.();
  };
};
