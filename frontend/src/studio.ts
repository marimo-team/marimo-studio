import {
  previewLoadState,
  RefreshRetrySchedule,
} from "./shell-refresh-state.ts";

interface ViewList {
  schema: 1;
  default_view: string;
  views: string[];
}

interface ViewDiagnostic {
  message: string;
}

const studio = document.querySelector<HTMLElement>("[data-studio]");
const workspace = document.querySelector<HTMLElement>(".studio-workspace");
const editor = document.querySelector<HTMLIFrameElement>("[data-editor-frame]");
const preview = document.querySelector<HTMLIFrameElement>(
  "[data-preview-frame]",
);
const selector = document.querySelector<HTMLSelectElement>(
  "[data-view-select]",
);
const popout = document.querySelector<HTMLAnchorElement>(
  "[data-preview-popout]",
);
const status = document.querySelector<HTMLElement>("[data-studio-status]");
const divider = document.querySelector<HTMLElement>("[data-divider]");

if (
  !studio ||
  !workspace ||
  !editor ||
  !preview ||
  !selector ||
  !popout ||
  !status ||
  !divider
) {
  throw new Error("Studio markup is incomplete");
}

const eventsUrl = studio.dataset.eventsUrl;
const viewsUrl = studio.dataset.viewsUrl;
const viewPrefix = studio.dataset.viewPrefix;
const studioPrefix = studio.dataset.studioPrefix;
const supportPrefix = studio.dataset.supportPrefix;
if (
  !eventsUrl ||
  !viewsUrl ||
  !viewPrefix ||
  !studioPrefix ||
  !supportPrefix
) {
  throw new Error("Studio route configuration is incomplete");
}

const viewUrl = (view: string) => `${viewPrefix}${view}/`;
const studioUrl = (view: string) => `${studioPrefix}${view}/`;
const supportUrl = (view: string) => `${supportPrefix}/${view}`;

const setStatus = (
  message = "",
  state: "loading" | "warning" | "error" = "loading",
  title = "",
) => {
  status.textContent = message;
  status.hidden = !message;
  if (message) {
    status.dataset.state = state;
  } else {
    delete status.dataset.state;
  }
  if (title) {
    status.title = title;
  } else {
    status.removeAttribute("title");
  }
};

let receiverReady = false;
let viewDiagnostics: ViewDiagnostic[] = [];
let previewRetryTimer: ReturnType<typeof setTimeout> | undefined;
const previewRetrySchedule = new RefreshRetrySchedule();

const cancelPreviewRetry = () => {
  if (previewRetryTimer !== undefined) {
    clearTimeout(previewRetryTimer);
    previewRetryTimer = undefined;
  }
};

const reloadPreview = () => {
  cancelPreviewRetry();
  receiverReady = false;
  setStatus("Connecting preview");
  preview.src = viewUrl(selector.value);
};

const schedulePreviewRetry = (delay = previewRetrySchedule.next()) => {
  cancelPreviewRetry();
  previewRetryTimer = setTimeout(() => {
    previewRetryTimer = undefined;
    if (!receiverReady) {
      reloadPreview();
    }
  }, delay);
};

const showViewStatus = () => {
  if (!viewDiagnostics.length) {
    setStatus();
    return;
  }
  const count = viewDiagnostics.length;
  setStatus(
    `${count} view ${count === 1 ? "issue" : "issues"}`,
    "warning",
    viewDiagnostics.map((diagnostic) => diagnostic.message).join("\n"),
  );
};

const postSwitch = (view: string) => {
  preview.contentWindow?.postMessage(
    {
      type: "marimo-studio:switch-view",
      view,
      documentUrl: viewUrl(view),
      supportUrl: supportUrl(view),
    },
    globalThis.location.origin,
  );
};

const setLayout = (layout: string) => {
  workspace.dataset.layoutState = layout;
  document.querySelectorAll<HTMLButtonElement>("[data-layout]").forEach(
    (button) => {
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.layout === layout),
      );
    },
  );
  globalThis.localStorage.setItem("marimo-studio:studio-layout", layout);
};

const selectView = (view: string) => {
  const nextPreview = viewUrl(view);
  preview.title = `${view} custom view`;
  popout.href = nextPreview;
  globalThis.history.replaceState({}, "", studioUrl(view));
  viewDiagnostics = [];
  setStatus("Updating preview");
  if (receiverReady) {
    postSwitch(view);
  } else {
    previewRetrySchedule.reset();
    reloadPreview();
  }
};

selector.addEventListener("change", () => selectView(selector.value));
document.querySelectorAll<HTMLButtonElement>("[data-layout]").forEach(
  (button) => {
    button.addEventListener("click", () => {
      const layout = button.dataset.layout;
      if (layout) {
        setLayout(layout);
      }
    });
  },
);

const initialLayout = globalThis.localStorage.getItem(
  "marimo-studio:studio-layout",
);
const narrow = globalThis.matchMedia("(max-width: 760px)");
setLayout(
  narrow.matches && (!initialLayout || initialLayout === "split")
    ? "editor"
    : initialLayout && ["editor", "split", "preview"].includes(initialLayout)
    ? initialLayout
    : "split",
);
narrow.addEventListener("change", (event) => {
  if (event.matches && workspace.dataset.layoutState === "split") {
    setLayout("editor");
  }
});

let dragging = false;
const resize = (clientX: number) => {
  const bounds = workspace.getBoundingClientRect();
  const percent = Math.min(
    80,
    Math.max(20, ((clientX - bounds.left) / bounds.width) * 100),
  );
  workspace.style.setProperty("--editor-width", `${percent}%`);
  divider.setAttribute("aria-valuenow", String(Math.round(percent)));
};
divider.addEventListener("pointerdown", (event) => {
  dragging = true;
  divider.setPointerCapture(event.pointerId);
});
divider.addEventListener("pointermove", (event) => {
  if (dragging) {
    resize(event.clientX);
  }
});
divider.addEventListener("pointerup", () => {
  dragging = false;
});
divider.addEventListener("keydown", (event) => {
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
    return;
  }
  event.preventDefault();
  const current = Number(divider.getAttribute("aria-valuenow") ?? "50");
  const next = Math.min(
    80,
    Math.max(20, current + (event.key === "ArrowRight" ? 2 : -2)),
  );
  workspace.style.setProperty("--editor-width", `${next}%`);
  divider.setAttribute("aria-valuenow", String(next));
});

globalThis.addEventListener("message", (event: MessageEvent<unknown>) => {
  if (
    event.origin !== globalThis.location.origin ||
    event.source !== preview.contentWindow
  ) {
    return;
  }
  const data = event.data;
  if (typeof data !== "object" || data === null || !("type" in data)) {
    return;
  }
  if (data.type === "marimo-studio:receiver-ready") {
    receiverReady = true;
    cancelPreviewRetry();
    previewRetrySchedule.reset();
    const active = "view" in data && typeof data.view === "string"
      ? data.view
      : undefined;
    if (active === selector.value) {
      showViewStatus();
    } else {
      postSwitch(selector.value);
    }
    return;
  }
  if (
    !("view" in data) ||
    typeof data.view !== "string" ||
    data.view !== selector.value
  ) {
    return;
  }
  if (data.type === "marimo-studio:view-ready") {
    showViewStatus();
  } else if (
    data.type === "marimo-studio:view-sync-pending" &&
    "message" in data &&
    typeof data.message === "string"
  ) {
    setStatus(
      "Waiting for notebook",
      "loading",
      "hint" in data && typeof data.hint === "string"
        ? data.hint
        : data.message,
    );
  } else if (
    data.type === "marimo-studio:view-diagnostics" &&
    "diagnostics" in data &&
    Array.isArray(data.diagnostics) &&
    data.diagnostics.every((diagnostic) =>
      typeof diagnostic === "object" &&
      diagnostic !== null &&
      "message" in diagnostic &&
      typeof diagnostic.message === "string"
    )
  ) {
    viewDiagnostics = data.diagnostics as ViewDiagnostic[];
    showViewStatus();
  } else if (
    data.type === "marimo-studio:view-error" &&
    "message" in data &&
    typeof data.message === "string"
  ) {
    setStatus(
      data.message,
      "error",
      "hint" in data && typeof data.hint === "string" ? data.hint : "",
    );
  }
});

const refreshViews = async () => {
  const response = await fetch(viewsUrl, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`View list failed with ${response.status}`);
  }
  const payload = await response.json() as ViewList;
  const current = selector.value;
  selector.replaceChildren(
    ...payload.views.map((view) =>
      new Option(view, view, false, view === current)
    ),
  );
  if (!payload.views.includes(current)) {
    selector.value = payload.default_view;
    selectView(payload.default_view);
  }
};

const events = new EventSource(eventsUrl);
events.addEventListener("change", () => {
  void refreshViews()
    .then(() => {
      if (!receiverReady) {
        previewRetrySchedule.reset();
        reloadPreview();
      }
    })
    .catch((error: unknown) => {
      setStatus(
        error instanceof Error ? error.message : String(error),
        "error",
      );
    });
});
globalThis.addEventListener(
  "pagehide",
  () => {
    cancelPreviewRetry();
    events.close();
  },
  { once: true },
);

const startPreview = () => {
  if (preview.src === "about:blank") {
    reloadPreview();
  }
};
preview.addEventListener("load", () => {
  if (receiverReady) {
    return;
  }
  const previewDocument = preview.contentDocument;
  const state = previewLoadState({
    hasRuntimeRoot: Boolean(
      previewDocument?.querySelector("#marimo-runtime-root"),
    ),
    documentState: previewDocument?.documentElement.dataset
      .marimoStudioPreviewState,
  });
  if (state === "ready") {
    schedulePreviewRetry(10_000);
    return;
  }
  const repair = previewDocument?.querySelector<HTMLElement>(
    "[data-marimo-studio-repair]",
  );
  const detail = repair
    ? [repair.dataset.marimoStudioMessage, repair.dataset.marimoStudioHint]
      .filter(Boolean)
      .join(" ")
    : previewDocument?.querySelector<HTMLElement>(
      "main, [role='status'], body > p",
    )?.textContent?.trim() ?? "";
  if (state === "waiting") {
    setStatus("Waiting for notebook", "loading", detail);
    schedulePreviewRetry(500);
    return;
  }
  setStatus("Preview needs repair", "error", detail);
  schedulePreviewRetry();
});
editor.addEventListener("load", startPreview, { once: true });
if (editor.contentDocument?.readyState === "complete") {
  startPreview();
}
