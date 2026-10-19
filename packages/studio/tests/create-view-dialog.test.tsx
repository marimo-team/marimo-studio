import type { Starter } from "@marimo-studio/protocol/provider-catalog";

import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vite-plus/test";

import type { ViewRemote } from "../src/features/views/remote.ts";

import { ViewController } from "../src/features/views/controller.ts";
import { ViewMenu } from "../src/features/views/ViewMenu.tsx";
import { STARTER_PREVIEW_URL, componentStarter, starter, viewList } from "./fixtures.ts";

const report: Starter = {
  ...starter,
  id: "acme-views/report:default",
  provider: "acme-views/report",
  title: "Paged report",
  summary: "A PDF report that lays out notebook values.",
  documents: ["main.typ"],
  format: "PDF",
  preview: "a".repeat(64),
  homepage: "https://typst.app/docs",
  settings: [
    {
      key: "paper",
      label: "Paper size",
      help: "The page size of the PDF.",
      kind: "choice",
      default: "a4",
      choices: [
        { value: "a4", label: "A4" },
        { value: "us-letter", label: "US Letter" },
      ],
    },
    {
      key: "toc",
      label: "Table of contents",
      help: "Lists the report's headings before its first page.",
      kind: "boolean",
      default: false,
      choices: [],
    },
  ],
};

const openDialog = async (starters: readonly Starter[], create: ViewRemote["create"] = vi.fn()) => {
  const remote: ViewRemote = {
    list: vi.fn(async () => viewList(["dashboard"], "dashboard", starters, starters[0]!.id)),
    create,
    remove: vi.fn(),
  };
  const controller = new ViewController(
    "dashboard",
    ["dashboard"],
    remote,
    vi.fn(async () => true),
    vi.fn(async () => true),
    vi.fn(),
    starters,
    starters[0]!.id,
  );
  await controller.refreshInventory();
  const user = userEvent.setup();
  render(<ViewMenu controller={controller} starterPreview={STARTER_PREVIEW_URL} />);
  await user.click(screen.getByLabelText(/^Switch view:/));
  await user.click(screen.getByRole("button", { name: "New view" }));
  return { controller, user };
};

it("sends the title, starter settings, and default choice with Create view", async () => {
  const create = vi.fn<ViewRemote["create"]>(async ({ name }) => ({ schema: 1, name }));
  const { controller, user } = await openDialog([report], create);

  await user.type(screen.getByLabelText("Name"), "quarterly");
  expect(screen.getByLabelText("Title")).toHaveAttribute("placeholder", "Quarterly");
  await user.type(screen.getByLabelText("Title"), "Quarterly report");
  await user.click(screen.getByRole("radio", { name: "US Letter" }));
  await user.click(screen.getByRole("switch", { name: "Table of contents" }));
  await user.click(screen.getByRole("switch", { name: "Default view" }));
  await user.click(screen.getByRole("button", { name: "Create view" }));

  await vi.waitFor(() => expect(create).toHaveBeenCalledOnce());
  expect(create.mock.calls[0]![0]).toEqual({
    catalog_generation: controller.getSnapshot().catalogGeneration,
    name: "quarterly",
    starter: report.id,
    title: "Quarterly report",
    settings: { paper: "us-letter", toc: true },
    make_default: true,
  });
  controller.dispose();
});

it("describes each setting with the help text it shows on demand", async () => {
  const { controller } = await openDialog([report]);

  expect(screen.getByRole("switch", { name: "Table of contents" })).toHaveAccessibleDescription(
    "Lists the report's headings before its first page.",
  );
  expect(screen.getByRole("radiogroup", { name: "Paper size" })).toHaveAccessibleDescription(
    "The page size of the PDF.",
  );
  expect(screen.getByLabelText("Title")).toHaveAccessibleDescription(/view name/);
  controller.dispose();
});

it("keeps settings per starter while a person compares starters", async () => {
  const { controller, user } = await openDialog([report, starter]);

  await user.click(screen.getByRole("radio", { name: "US Letter" }));
  await user.click(screen.getByRole("radio", { name: /HTML/ }));
  expect(screen.queryByRole("radiogroup", { name: "Paper size" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("radio", { name: /Paged report/ }));

  expect(screen.getByRole("radio", { name: "US Letter" })).toBeChecked();
  controller.dispose();
});

it("loads a starter preview by its revision and links the technology", async () => {
  const { controller } = await openDialog([report]);

  const preview = screen.getByRole("img", { name: "Preview of a view created from Paged report" });
  const url = new URL(preview.getAttribute("src")!);
  expect(url.searchParams.get("starter")).toBe(report.id);
  expect(url.searchParams.get("revision")).toBe(report.preview);
  expect(screen.getByRole("link", { name: /typst\.app/ })).toHaveAttribute(
    "href",
    "https://typst.app/docs",
  );
  controller.dispose();
});

it("filters starters by title, format, and documents", async () => {
  const { controller, user } = await openDialog([report, starter, componentStarter]);

  const starters = screen.getByRole("group", { name: "Starter" });
  await user.type(screen.getByRole("searchbox", { name: "Search starters" }), "pdf");
  expect(
    within(starters)
      .getAllByRole("radio")
      .map((radio) => radio.getAttribute("value")),
  ).toEqual([report.id]);
  await user.clear(screen.getByRole("searchbox", { name: "Search starters" }));
  await user.type(screen.getByRole("searchbox", { name: "Search starters" }), "app.tsx");
  expect(screen.getByRole("radio", { name: /Component project/ })).toBeInTheDocument();
  expect(screen.queryByRole("radio", { name: /Paged report/ })).not.toBeInTheDocument();
  controller.dispose();
});

it("ignores Escape while a create is pending and closes on Escape otherwise", async () => {
  let finish: (value: { schema: 1; name: string }) => void = () => {};
  const create = vi.fn<ViewRemote["create"]>(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const { controller, user } = await openDialog([starter], create);
  const dialog = screen.getByRole("dialog", { name: "New view" });

  await user.type(screen.getByLabelText("Name"), "pending");
  await user.click(screen.getByRole("button", { name: "Create view" }));
  await screen.findByRole("button", { name: "Creating…" });
  fireEvent(dialog, new Event("cancel", { cancelable: true }));
  expect(dialog).toHaveAttribute("open");

  finish({ schema: 1, name: "pending" });
  await vi.waitFor(() => expect(dialog).not.toHaveAttribute("open"));
  await user.click(screen.getByLabelText(/^Switch view:/));
  await user.click(screen.getByRole("button", { name: "New view" }));
  fireEvent(dialog, new Event("cancel", { cancelable: true }));
  expect(dialog).not.toHaveAttribute("open");
  controller.dispose();
});
