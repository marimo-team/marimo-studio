interface DocumentPresenceCallbacks {
  ready(): void;
  unready(): void;
  dispose(): void;
}

export const onFinalPageHide = (dispose: () => void): (() => void) => {
  const pagehide = (event: PageTransitionEvent) => {
    if (event.persisted) {
      return;
    }
    globalThis.removeEventListener("pagehide", pagehide);
    dispose();
  };
  globalThis.addEventListener("pagehide", pagehide);
  return () => globalThis.removeEventListener("pagehide", pagehide);
};

export const bindDocumentPresence = (callbacks: DocumentPresenceCallbacks): (() => void) => {
  let final = false;
  const pagehide = (event: PageTransitionEvent) => {
    callbacks.unready();
    if (event.persisted) {
      return;
    }
    final = true;
    unbind();
    callbacks.dispose();
  };
  const pageshow = (event: PageTransitionEvent) => {
    if (event.persisted && !final) {
      callbacks.ready();
    }
  };
  const unbind = () => {
    globalThis.removeEventListener("pagehide", pagehide);
    globalThis.removeEventListener("pageshow", pageshow);
  };
  globalThis.addEventListener("pagehide", pagehide);
  globalThis.addEventListener("pageshow", pageshow);
  callbacks.ready();
  return unbind;
};
