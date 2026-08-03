interface ViewMenuActions {
  choose(view: string): void;
  create(name: string): void;
  beginRemoval(view: string): void;
  cancelRemoval(): void;
  confirmRemoval(): void;
  dismiss(): void;
}

export class ViewMenu {
  private readonly menu = document.querySelector<HTMLDetailsElement>("[data-view-menu]");
  private readonly add = document.querySelector<HTMLButtonElement>("[data-new-view]");
  private readonly form = document.querySelector<HTMLFormElement>("[data-new-view-form]");
  private readonly input = document.querySelector<HTMLInputElement>("[data-new-view-name]");

  constructor(private readonly actions: ViewMenuActions) {
    this.bind();
  }

  render(current: string, views: string[], removing: string | undefined, deleting: boolean): void {
    const trigger = document.querySelector<HTMLElement>("[data-view-trigger-label]");
    if (trigger) {
      trigger.textContent = current;
    }
    const list = document.querySelector<HTMLElement>("[data-view-list]");
    if (!list) {
      return;
    }
    list.replaceChildren(
      ...views.map((view) => this.viewRow(view, current, removing, deleting, views.length > 1)),
    );
  }

  showRemoval(name: string): void {
    this.resetCreate();
    const confirmation = document.querySelector<HTMLElement>("[data-remove-view-confirm]");
    const label = document.querySelector<HTMLElement>("[data-remove-view-name]");
    if (confirmation) {
      confirmation.hidden = false;
    }
    if (label) {
      label.textContent = name;
    }
    if (this.add) {
      this.add.hidden = true;
    }
    this.clearRemovalError();
    document.querySelector<HTMLButtonElement>("[data-remove-view-submit]")?.focus();
  }

  hideRemoval(focusView?: string): void {
    const confirmation = document.querySelector<HTMLElement>("[data-remove-view-confirm]");
    const label = document.querySelector<HTMLElement>("[data-remove-view-name]");
    if (confirmation) {
      confirmation.hidden = true;
      confirmation.setAttribute("aria-busy", "false");
    }
    if (label) {
      label.textContent = "";
    }
    if (this.add && (this.form?.hidden ?? true)) {
      this.add.hidden = false;
    }
    this.clearRemovalError();
    if (focusView) {
      document
        .querySelector<HTMLButtonElement>(`[data-remove-view="${CSS.escape(focusView)}"]`)
        ?.focus();
    }
  }

  resetCreate(): void {
    const message = document.querySelector<HTMLElement>("[data-new-view-message]");
    this.form?.reset();
    if (this.form) {
      this.form.hidden = true;
    }
    const removal = document.querySelector<HTMLElement>("[data-remove-view-confirm]");
    if (this.add && (removal?.hidden ?? true)) {
      this.add.hidden = false;
    }
    if (message) {
      message.hidden = true;
      message.textContent = "";
      delete message.dataset.state;
      message.setAttribute("role", "status");
    }
    this.input?.setCustomValidity("");
  }

  showCreateMessage(message: string, state: "warning" | "error"): void {
    const element = document.querySelector<HTMLElement>("[data-new-view-message]");
    if (element) {
      element.hidden = false;
      element.dataset.state = state;
      element.setAttribute("role", state === "error" ? "alert" : "status");
      element.textContent = message;
    }
  }

  clearCreateMessage(): void {
    const element = document.querySelector<HTMLElement>("[data-new-view-message]");
    if (element) {
      element.hidden = true;
      element.textContent = "";
      delete element.dataset.state;
    }
  }

  showRemovalError(message: string): void {
    const element = document.querySelector<HTMLElement>("[data-remove-view-message]");
    if (element) {
      element.hidden = false;
      element.dataset.state = "error";
      element.textContent = message;
    }
  }

  clearRemovalError(): void {
    const element = document.querySelector<HTMLElement>("[data-remove-view-message]");
    if (element) {
      element.hidden = true;
      element.textContent = "";
      delete element.dataset.state;
    }
  }

  setCreating(creating: boolean): void {
    const submit = document.querySelector<HTMLButtonElement>("[data-new-view-submit]");
    this.form?.setAttribute("aria-busy", String(creating));
    if (submit) {
      submit.disabled = creating;
      submit.textContent = creating ? "Creating…" : "Create";
    }
  }

  setDeleting(deleting: boolean): void {
    const confirmation = document.querySelector<HTMLElement>("[data-remove-view-confirm]");
    const submit = document.querySelector<HTMLButtonElement>("[data-remove-view-submit]");
    confirmation?.setAttribute("aria-busy", String(deleting));
    if (submit) {
      submit.disabled = deleting;
      submit.textContent = deleting ? "Removing…" : "Remove";
    }
    document.querySelectorAll<HTMLButtonElement>("[data-remove-view]").forEach((button) => {
      button.disabled = deleting;
    });
  }

  close(): void {
    this.menu?.removeAttribute("open");
  }

  private bind(): void {
    this.add?.addEventListener("click", () => {
      this.actions.dismiss();
      this.hideRemoval();
      if (this.form) {
        this.form.hidden = false;
      }
      this.add!.hidden = true;
      this.input?.focus();
    });
    document
      .querySelector<HTMLButtonElement>("[data-new-view-cancel]")
      ?.addEventListener("click", () => this.resetCreate());
    this.form?.addEventListener("submit", (event) => {
      event.preventDefault();
      this.actions.create(this.input?.value ?? "");
    });
    document
      .querySelector<HTMLButtonElement>("[data-remove-view-cancel]")
      ?.addEventListener("click", () => this.actions.cancelRemoval());
    document
      .querySelector<HTMLButtonElement>("[data-remove-view-submit]")
      ?.addEventListener("click", () => this.actions.confirmRemoval());
    this.menu?.addEventListener("toggle", () => {
      if (!this.menu?.open) {
        this.resetCreate();
        this.hideRemoval();
        this.actions.dismiss();
      }
    });
  }

  private viewRow(
    view: string,
    current: string,
    removing: string | undefined,
    deleting: boolean,
    removable: boolean,
  ): HTMLElement {
    const row = document.createElement("div");
    row.className = "studio-view-row";
    if (view === removing) {
      row.dataset.removing = "true";
    }
    const option = document.createElement("button");
    option.type = "button";
    option.className = "studio-menu-item studio-view-option";
    option.dataset.viewOption = view;
    if (view === current) {
      option.setAttribute("aria-current", "page");
    }
    const check = document.createElement("span");
    check.className = "studio-menu-check";
    check.textContent = "✓";
    option.append(check, view);
    option.addEventListener("click", () => this.actions.choose(view));
    row.append(option);
    if (removable) {
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "studio-view-remove";
      remove.dataset.removeView = view;
      remove.setAttribute("aria-label", `Remove ${view} view`);
      remove.textContent = "Remove";
      remove.disabled = deleting;
      remove.addEventListener("click", (event) => {
        event.stopPropagation();
        this.actions.beginRemoval(view);
      });
      row.append(remove);
    }
    return row;
  }
}
