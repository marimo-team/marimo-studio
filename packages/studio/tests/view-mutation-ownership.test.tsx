import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vite-plus/test";

import type { ViewRemote } from "../src/features/views/remote.ts";

import { ViewController } from "../src/features/views/controller.ts";
import { ViewMenu } from "../src/features/views/ViewMenu.tsx";
import { starter, viewList } from "./fixtures.ts";

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
  const user = userEvent.setup();
  render(<ViewMenu controller={controller} />);

  expect(screen.getByLabelText("Switch page: dashboard")).toHaveTextContent("dashboard");
  await user.click(screen.getByLabelText(/^Switch page:/));
  expect(screen.getByRole("button", { name: "dashboard, default" })).toBeVisible();
  expect(screen.getByRole("button", { name: "New page" })).toBeVisible();
  expect(screen.getByLabelText("Remove report page")).toBeInTheDocument();
  screen.getByRole("button", { name: "New page" }).focus();
  await user.keyboard("{Escape}");
  expect(screen.getByLabelText(/^Switch page:/)).toHaveFocus();
  expect(screen.getByLabelText(/^Switch page:/).closest("details")?.open).toBe(false);
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
  const user = userEvent.setup();
  render(<ViewMenu controller={controller} />);
  const menu = screen.getByLabelText(/^Switch page:/).closest("details");
  expect(menu).not.toBeNull();

  await user.click(screen.getByLabelText(/^Switch page:/));
  await user.click(screen.getByRole("button", { name: "report" }));

  expect(menu?.open).toBe(false);
  expect(controller.getSnapshot().selecting).toBe("report");
  await user.click(screen.getByLabelText(/^Switch page:/));
  expect(screen.getByRole("button", { name: "report, loading" })).toHaveAttribute(
    "aria-busy",
    "true",
  );
  selected.resolve(true);
  await vi.waitFor(() => expect(screen.getByLabelText("Switch page: report")).toBeVisible());
  expect(menu?.open).toBe(true);
  expect(controller.getSnapshot().selecting).toBeUndefined();
  controller.dispose();
});

it.each([
  ["returns false", async (): Promise<boolean> => false, /Could not open report/],
  [
    "rejects",
    async (): Promise<boolean> => Promise.reject(new Error("Preview failed")),
    /Preview failed/,
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
    const user = userEvent.setup();
    render(<ViewMenu controller={controller} />);
    const menu = screen.getByLabelText(/^Switch page:/).closest("details");

    await user.click(screen.getByLabelText(/^Switch page:/));
    await user.click(screen.getByRole("button", { name: "report" }));

    expect(menu?.open).toBe(false);
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    controller.dispose();
  },
);

it("keeps a newer create panel open when an earlier view selection settles", async () => {
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
  const user = userEvent.setup();
  render(<ViewMenu controller={controller} />);

  await user.click(screen.getByLabelText(/^Switch page:/));
  await user.click(screen.getByRole("button", { name: "report" }));
  await user.click(screen.getByLabelText(/^Switch page:/));
  await user.click(screen.getByRole("button", { name: "New page" }));
  selected.resolve(true);

  await vi.waitFor(() => expect(screen.getByLabelText("New page")).toBeVisible());
  expect(screen.getByLabelText(/^Switch page:/).closest("details")?.open).toBe(true);
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
  const user = userEvent.setup();
  render(<ViewMenu controller={controller} />);

  await user.click(screen.getByLabelText(/^Switch page:/));
  await user.click(screen.getByRole("button", { name: "report" }));
  await user.click(screen.getByLabelText(/^Switch page:/));
  await user.click(screen.getByLabelText("Remove report page"));
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
    const user = userEvent.setup();
    render(<ViewMenu controller={controller} />);
    const menu = screen.getByLabelText(/^Switch page:/).closest("details");
    expect(menu).not.toBeNull();
    await user.click(screen.getByLabelText(/^Switch page:/));
    await user.click(screen.getByRole("button", { name: "New page" }));
    await user.type(screen.getByLabelText("New page"), "created");
    await user.click(screen.getByRole("button", { name: "Create" }));
    expect(await screen.findByRole("button", { name: "Creating…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.getByLabelText(/^Switch page:/)).toHaveAttribute("aria-disabled", "true");

    await user.click(screen.getByLabelText(/^Switch page:/));
    expect(menu?.open).toBe(true);

    if (outcome === "success") {
      created.resolve({
        schema: 1,
        name: "created",
      });
      await vi.waitFor(() => expect(menu?.open).toBe(false));
    } else {
      created.reject(new Error("create failed"));
      expect(await screen.findByRole("alert")).toHaveTextContent("create failed");
      expect(menu?.open).toBe(true);
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
    const user = userEvent.setup();
    render(<ViewMenu controller={controller} />);
    const menu = screen.getByLabelText(/^Switch page:/).closest("details");
    expect(menu).not.toBeNull();
    await user.click(screen.getByLabelText(/^Switch page:/));
    await user.click(screen.getByLabelText("Remove report page"));
    expect(screen.getByText(/permanently deletes/)).toHaveTextContent("report");
    await user.click(screen.getByRole("button", { name: "Remove" }));
    expect(await screen.findByRole("button", { name: "Removing…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.getByLabelText(/^Switch page:/)).toHaveAttribute("aria-disabled", "true");

    await user.click(screen.getByLabelText(/^Switch page:/));
    expect(menu?.open).toBe(true);

    if (outcome === "success") {
      removed.resolve({ ...viewList(["dashboard"]), name: "report" });
      await vi.waitFor(() => expect(menu?.open).toBe(false));
    } else {
      removed.reject(new Error("remove failed"));
      expect(await screen.findByRole("alert")).toHaveTextContent("remove failed");
      expect(menu?.open).toBe(true);
      expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();
    }
    controller.dispose();
  },
);
