interface Rectangle {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** Observe native overlays and size the notebook independently of Marimo's panels. */
export const connectMarimoEditorWorkspace = (
  frame: HTMLIFrameElement,
  onBounds: (bounds: Rectangle | undefined) => void,
  onDialog: (open: boolean) => void,
  onNotification: (bounds: Rectangle | undefined) => void,
) => {
  let disposeDocument = () => {};
  let notebook: HTMLElement | null = null;
  let bounds: Rectangle | undefined;
  let placement: Rectangle | undefined;
  let placed = false;
  let closed = false;
  const apply = () => {
    if (closed || !notebook || !bounds || !placed) return;
    notebook.inert = placement === undefined;
    notebook.style.visibility = placement ? "" : "hidden";
    if (!placement) return;
    notebook.style.width = `${placement.width}px`;
    notebook.style.marginLeft = `${placement.left - bounds.left}px`;
    notebook.style.borderTop = `${Math.max(0, placement.top - bounds.top)}px solid transparent`;
    notebook.style.borderBottom = `${Math.max(0, bounds.top + bounds.height - placement.top - placement.height)}px solid transparent`;
  };
  const connect = () => {
    if (closed) return;
    disposeDocument();
    notebook = null;
    bounds = undefined;
    onBounds(undefined);
    onDialog(false);
    onNotification(undefined);
    const doc = frame.contentDocument;
    if (!doc) return;
    let resize: ResizeObserver | undefined;
    let restore = () => {};
    let container: HTMLElement | null = null;
    let notifications: HTMLElement | null = null;
    const measureNotifications = () => {
      if (closed) return;
      onNotification(notifications?.getBoundingClientRect());
    };
    const notificationResize = new ResizeObserver(measureNotifications);
    doc.defaultView?.addEventListener("resize", measureNotifications);
    const discover = () => {
      onDialog(
        doc.querySelector(
          '[role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"], dialog[open], [data-testid="chrome-context-aware-panel"]',
        ) !== null,
      );
      const viewport = doc.querySelector<HTMLElement>(
        'ol:has(> li[data-swipe-direction][data-state="open"])',
      );
      if (viewport !== notifications) {
        notificationResize.disconnect();
        notifications = viewport;
        if (viewport) notificationResize.observe(viewport);
        measureNotifications();
      }
      const app = doc.getElementById("app");
      const body = doc.getElementById("app-chrome-body");
      const developer = doc.getElementById("app-chrome-panel");
      if (!app || !body || !developer || (container === body && notebook === app)) return;
      resize?.disconnect();
      restore();
      container = body;
      notebook = app;
      const original = {
        width: app.style.width,
        marginLeft: app.style.marginLeft,
        borderTop: app.style.borderTop,
        borderBottom: app.style.borderBottom,
        visibility: app.style.visibility,
        inert: app.inert,
      };
      restore = () => {
        const { inert, ...styles } = original;
        Object.assign(app.style, styles);
        app.inert = inert;
      };
      const measure = () => {
        if (closed) return;
        const rectangle = body.getBoundingClientRect();
        const panel = developer.getBoundingClientRect();
        const next = {
          left: rectangle.left,
          top: rectangle.top,
          width: rectangle.width,
          height: rectangle.height - panel.height,
        };
        if (
          !bounds ||
          next.left !== bounds.left ||
          next.top !== bounds.top ||
          next.width !== bounds.width ||
          next.height !== bounds.height
        ) {
          bounds = next;
          onBounds(next);
          apply();
        }
      };
      resize = new ResizeObserver(measure);
      resize.observe(body);
      resize.observe(developer);
      measure();
    };
    const observer = new MutationObserver(discover);
    observer.observe(doc, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["role", "data-state", "open"],
    });
    discover();
    disposeDocument = () => {
      observer.disconnect();
      notificationResize.disconnect();
      doc.defaultView?.removeEventListener("resize", measureNotifications);
      resize?.disconnect();
      restore();
    };
  };
  frame.addEventListener("load", connect);
  connect();
  return {
    placeNotebook(rectangle: Rectangle | undefined) {
      placement = rectangle;
      placed = true;
      apply();
    },
    close() {
      if (closed) return;
      closed = true;
      frame.removeEventListener("load", connect);
      disposeDocument();
      onDialog(false);
      onNotification(undefined);
    },
  };
};
