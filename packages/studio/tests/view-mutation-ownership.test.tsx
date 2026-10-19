import type { CreateViewRequest } from "@marimo-studio/protocol/views";

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vite-plus/test";

import type { ViewRemote } from "../src/features/views/remote.ts";

import { ViewController } from "../src/features/views/controller.ts";
import { ViewMenu } from "../src/features/views/ViewMenu.tsx";
import { STARTER_PREVIEW_URL, starter, viewGeneration, viewList } from "./fixtures.ts";

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (cause: Error) => void;
  const promise = new Promise<T>((complete, fail) => {
    resolve = complete;
    reject = fail;
  });
  return { promise, reject, resolve };
};

it("keeps creation and removal directly available in the switcher", async () => {
  const remote: ViewRemote = {
    list: vi.fn(async () => viewList(["dashboard", "report"])),
    create: vi.fn(),
    remove: vi.fn(),
  };
  const controller = new ViewController(
    "dashboard",
    ["dashboard", "report"],
    remote,
    vi.fn(async () => true),
    vi.fn(async () => true),
    vi.fn(),
    [starter],
    starter.id,
  );
  await controller.refreshInventory();
  const user = userEvent.setup();
  render(<ViewMenu controller={controller} starterPreview={STARTER_PREVIEW_URL} />);

  expect(screen.getByLabelText("Switch view: dashboard")).toHaveTextContent("dashboard");
  await user.click(screen.getByLabelText(/^Switch view:/));
  expect(screen.getByRole("button", { name: "dashboard, default" })).toBeVisible();
  expect(screen.getByRole("button", { name: "New view" })).toBeVisible();
  expect(screen.getByLabelText("Remove report view")).toBeInTheDocument();
  screen.getByRole("button", { name: "New view" }).focus();
  await user.keyboard("{Escape}");
  expect(screen.getByLabelText(/^Switch view:/)).toHaveFocus();
  expect(screen.getByLabelText(/^Switch view:/).closest("details")?.open).toBe(false);
  controller.dispose();
});

it("closes immediately while a selected view loads and can reopen on its pending state", async () => {
  const selected = deferred<boolean>();
  const remote: ViewRemote = {
    list: vi.fn(async () => viewList(["dashboard", "report"])),
    create: vi.fn(),
    remove: vi.fn(),
  };
  const controller = new ViewController(
    "dashboard",
    ["dashboard", "report"],
    remote,
    vi.fn(() => selected.promise),
    vi.fn(async () => true),
    vi.fn(),
    [starter],
    starter.id,
  );
  await controller.refreshInventory();
  const user = userEvent.setup();
  render(<ViewMenu controller={controller} starterPreview={STARTER_PREVIEW_URL} />);
  const menu = screen.getByLabelText(/^Switch view:/).closest("details");
  expect(menu).not.toBeNull();

  await user.click(screen.getByLabelText(/^Switch view:/));
  await user.click(screen.getByRole("button", { name: "report" }));

  expect(menu?.open).toBe(false);
  expect(controller.getSnapshot().selecting).toBe("report");
  await user.click(screen.getByLabelText(/^Switch view:/));
  expect(screen.getByRole("button", { name: "report, loading" })).toHaveAttribute(
    "aria-busy",
    "true",
  );
  selected.resolve(true);
  await vi.waitFor(() => expect(screen.getByLabelText("Switch view: report")).toBeVisible());
  expect(menu?.open).toBe(true);
  expect(controller.getSnapshot().selecting).toBeUndefined();
  controller.dispose();
});

it.each([
  ["returns false", async (): Promise<boolean> => false, "report"],
  [
    "rejects",
    async (): Promise<boolean> => Promise.reject(new Error("Preview failed")),
    "Preview failed",
  ],
] as const)(
  "surfaces a persistent selection error when choosing a view %s",
  async (_, select, text) => {
    const remote: ViewRemote = {
      list: vi.fn(async () => viewList(["dashboard", "report"])),
      create: vi.fn(),
      remove: vi.fn(),
    };
    const controller = new ViewController(
      "dashboard",
      ["dashboard", "report"],
      remote,
      vi.fn(select),
      vi.fn(async () => true),
      vi.fn(),
      [starter],
      starter.id,
    );
    await controller.refreshInventory();
    const user = userEvent.setup();
    render(<ViewMenu controller={controller} starterPreview={STARTER_PREVIEW_URL} />);
    const menu = screen.getByLabelText(/^Switch view:/).closest("details");

    await user.click(screen.getByLabelText(/^Switch view:/));
    await user.click(screen.getByRole("button", { name: "report" }));

    expect(menu?.open).toBe(false);
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    controller.dispose();
  },
);

it("keeps a newer New view dialog open when an earlier view selection settles", async () => {
  const selected = deferred<boolean>();
  const cancelSelection = vi.fn();
  const remote: ViewRemote = {
    list: vi.fn(async () => viewList(["dashboard", "report"])),
    create: vi.fn(),
    remove: vi.fn(),
  };
  const controller = new ViewController(
    "dashboard",
    ["dashboard", "report"],
    remote,
    vi.fn(() => selected.promise),
    vi.fn(async () => true),
    cancelSelection,
    [starter],
    starter.id,
  );
  await controller.refreshInventory();
  const user = userEvent.setup();
  render(<ViewMenu controller={controller} starterPreview={STARTER_PREVIEW_URL} />);

  await user.click(screen.getByLabelText(/^Switch view:/));
  await user.click(screen.getByRole("button", { name: "report" }));
  await user.click(screen.getByLabelText(/^Switch view:/));
  await user.click(screen.getByRole("button", { name: "New view" }));
  selected.resolve(true);

  await vi.waitFor(() => expect(screen.getByLabelText("Name")).toBeVisible());
  expect(screen.getByRole("dialog", { name: "New view" })).toHaveAttribute("open");
  expect(cancelSelection).toHaveBeenCalledTimes(1);
  controller.dispose();
});

it("keeps direct removal open when an earlier view selection settles", async () => {
  const selected = deferred<boolean>();
  const cancelSelection = vi.fn();
  const remote: ViewRemote = {
    list: vi.fn(async () => viewList(["dashboard", "report"])),
    create: vi.fn(),
    remove: vi.fn(),
  };
  const controller = new ViewController(
    "dashboard",
    ["dashboard", "report"],
    remote,
    vi.fn(() => selected.promise),
    vi.fn(async () => true),
    cancelSelection,
    [starter],
    starter.id,
  );
  await controller.refreshInventory();
  const user = userEvent.setup();
  render(<ViewMenu controller={controller} starterPreview={STARTER_PREVIEW_URL} />);

  await user.click(screen.getByLabelText(/^Switch view:/));
  await user.click(screen.getByRole("button", { name: "report" }));
  await user.click(screen.getByLabelText(/^Switch view:/));
  await user.click(screen.getByLabelText("Remove report view"));
  selected.resolve(true);

  await vi.waitFor(() => expect(screen.getByRole("button", { name: "Remove" })).toBeVisible());
  expect(screen.getByText(/permanently deletes/)).toHaveTextContent("report");
  expect(cancelSelection).toHaveBeenCalledTimes(1);
  controller.dispose();
});

it.each(["success", "failure"] as const)(
  "keeps a pending create visibly owned through %s",
  async (outcome) => {
    const created = deferred<Awaited<ReturnType<ViewRemote["create"]>>>();
    const remote: ViewRemote = {
      list: vi.fn(async () => viewList(["dashboard", "created"])),
      create: vi.fn(() => created.promise),
      remove: vi.fn(),
    };
    const controller = new ViewController(
      "dashboard",
      ["dashboard"],
      remote,
      vi.fn(async () => true),
      vi.fn(async () => true),
      vi.fn(),
      [starter],
      starter.id,
    );
    await controller.refreshInventory();
    const user = userEvent.setup();
    render(<ViewMenu controller={controller} starterPreview={STARTER_PREVIEW_URL} />);
    const menu = screen.getByLabelText(/^Switch view:/).closest("details");
    expect(menu).not.toBeNull();
    await user.click(screen.getByLabelText(/^Switch view:/));
    await user.click(screen.getByRole("button", { name: "New view" }));
    await user.type(screen.getByLabelText("Name"), "created");
    await user.click(screen.getByRole("button", { name: "Create view" }));
    expect(await screen.findByRole("button", { name: "Creating…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.getByLabelText(/^Switch view:/)).toHaveAttribute("aria-disabled", "true");

    const dialog = screen.getByRole("dialog", { name: "New view" });
    await user.click(screen.getByLabelText(/^Switch view:/));
    expect(menu?.open).toBe(false);
    expect(dialog).toHaveAttribute("open");

    if (outcome === "success") {
      created.resolve({
        schema: 1,
        name: "created",
      });
      await vi.waitFor(() => expect(dialog).not.toHaveAttribute("open"));
    } else {
      created.reject(new Error("create failed"));
      expect(await screen.findByRole("alert")).toHaveTextContent("create failed");
      expect(dialog).toHaveAttribute("open");
      expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();
    }
    controller.dispose();
  },
);

it.each(["success", "failure"] as const)(
  "keeps a pending delete visibly owned through %s",
  async (outcome) => {
    const removed = deferred<Awaited<ReturnType<ViewRemote["remove"]>>>();
    const remote: ViewRemote = {
      list: vi.fn(async () => viewList(["dashboard", "report"])),
      create: vi.fn(),
      remove: vi.fn(() => removed.promise),
    };
    const controller = new ViewController(
      "dashboard",
      ["dashboard", "report"],
      remote,
      vi.fn(async () => true),
      vi.fn(async () => true),
      vi.fn(),
      [starter],
      starter.id,
    );
    await controller.refreshInventory();
    const user = userEvent.setup();
    render(<ViewMenu controller={controller} starterPreview={STARTER_PREVIEW_URL} />);
    const menu = screen.getByLabelText(/^Switch view:/).closest("details");
    expect(menu).not.toBeNull();
    await user.click(screen.getByLabelText(/^Switch view:/));
    await user.click(screen.getByLabelText("Remove report view"));
    expect(screen.getByText(/permanently deletes/)).toHaveTextContent("report");
    await user.click(screen.getByRole("button", { name: "Remove" }));
    expect(await screen.findByRole("button", { name: "Removing…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.getByLabelText(/^Switch view:/)).toHaveAttribute("aria-disabled", "true");

    await user.click(screen.getByLabelText(/^Switch view:/));
    expect(menu?.open).toBe(true);

    if (outcome === "success") {
      removed.resolve({
        ...viewList(["dashboard"]),
        cleanup: "/tmp/studio-delete-report",
        name: "report",
      });
      await vi.waitFor(() => expect(menu?.open).toBe(false));
      expect(remote.remove).toHaveBeenCalledWith("report", viewGeneration(0), viewGeneration(2));
      expect(screen.getByRole("alert")).toHaveTextContent("/tmp/studio-delete-report");
    } else {
      removed.reject(new Error("remove failed"));
      expect(await screen.findByRole("alert")).toHaveTextContent("remove failed");
      expect(menu?.open).toBe(true);
      expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();
    }
    controller.dispose();
  },
);

it.each([
  {
    notice: "clears a creation error",
    name: "dashboard",
    opened: true,
    rejected: true,
    role: "alert",
    remains: false,
  },
  {
    notice: "keeps the created-view warning",
    name: "report",
    opened: false,
    rejected: false,
    role: "status",
    remains: true,
  },
] as const)(
  "$notice after the view name changes",
  async ({ name, opened, rejected, role, remains }) => {
    const remote: ViewRemote = {
      list: vi.fn(async () => viewList(["dashboard"])),
      create: vi.fn(async ({ name: viewName }: CreateViewRequest) => {
        if (rejected) {
          throw new Error(`A view named '${viewName}' already exists.`);
        }
        return { schema: 1 as const, name: viewName };
      }),
      remove: vi.fn(),
    };
    const controller = new ViewController(
      "dashboard",
      ["dashboard"],
      remote,
      vi.fn(async () => opened),
      vi.fn(async () => true),
      vi.fn(),
      [starter],
      starter.id,
    );
    await controller.refreshInventory();
    const user = userEvent.setup();
    render(<ViewMenu controller={controller} starterPreview={STARTER_PREVIEW_URL} />);
    await user.click(screen.getByLabelText(/^Switch view:/));
    await user.click(screen.getByRole("button", { name: "New view" }));
    await user.type(screen.getByRole("textbox", { name: "Name" }), name);
    await user.click(screen.getByRole("button", { name: "Create view" }));
    const notice = await screen.findByRole(role);
    expect(notice).toBeVisible();

    await user.type(screen.getByRole("textbox", { name: "Name" }), "-2");

    if (remains) {
      expect(notice).toBeVisible();
    } else {
      expect(notice).not.toBeInTheDocument();
    }
    controller.dispose();
  },
);
