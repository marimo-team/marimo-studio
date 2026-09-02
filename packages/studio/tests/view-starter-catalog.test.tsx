import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vite-plus/test";

import type { ViewRemote } from "../src/features/views/remote.ts";

import { ViewController } from "../src/features/views/controller.ts";
import { ViewMenu } from "../src/features/views/ViewMenu.tsx";
import { starter, componentStarter, viewList } from "./fixtures.ts";

it("recovers the starter catalog after a failed Create refresh", async () => {
  const list = vi
    .fn<ViewRemote["list"]>()
    .mockRejectedValueOnce(new Error("Authoring options are temporarily unavailable."))
    .mockResolvedValue(viewList(["dashboard"]));
  const remote: ViewRemote = {
    list,
    create: vi.fn(),
    remove: vi.fn(),
  };
  const controller = new ViewController(
    "dashboard",
    ["dashboard"],
    remote,
    vi.fn(async () => true),
    vi.fn(async () => true),
    vi.fn(),
  );
  const user = userEvent.setup();
  render(<ViewMenu controller={controller} />);

  await user.click(screen.getByLabelText(/^Switch view:/));
  await user.click(screen.getByRole("button", { name: "New view" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Authoring options are temporarily unavailable.",
  );
  await user.click(screen.getByRole("button", { name: "Retry view choices" }));

  expect(await screen.findByRole("radio", { name: /HTML/ })).toBeChecked();
  expect(controller.getSnapshot().starterCatalog).toEqual({ phase: "ready" });
  expect(controller.getSnapshot().starters).toEqual([starter]);
  expect(list).toHaveBeenCalledTimes(2);
  controller.dispose();
});

it("reveals selected starter files on demand and keeps recovery actions local", async () => {
  const unavailable = {
    ...componentStarter,
    documents: ["src/App.tsx", "src/theme.css"],
    availability: {
      available: false,
      version: null,
      reason: "Deno is unavailable.",
      action: "Install Deno to use React.",
    },
  };
  const remote: ViewRemote = {
    list: vi.fn(async () => viewList(["dashboard"], "dashboard", [starter, unavailable])),
    create: vi.fn(),
    remove: vi.fn(),
  };
  const controller = new ViewController(
    "dashboard",
    ["dashboard"],
    remote,
    vi.fn(async () => true),
    vi.fn(async () => true),
    vi.fn(),
    [starter, unavailable],
    starter.id,
  );
  const user = userEvent.setup();
  render(<ViewMenu controller={controller} />);

  await user.click(screen.getByLabelText(/^Switch view:/));
  await user.click(screen.getByRole("button", { name: "New view" }));

  const react = screen.getByRole("radio", { name: /Component project/ }).closest("label");
  expect(react).toHaveTextContent("Install Deno to use React.");
  const details = screen.getByText("Files created").closest("details");
  expect(details?.open).toBe(false);
  await user.click(screen.getByText("Files created"));
  expect(details?.open).toBe(true);
  expect(details).toHaveTextContent("index.html");
  controller.dispose();
});

it("keeps a single-distribution starter catalog flat", async () => {
  const remote: ViewRemote = {
    list: vi.fn(async () => viewList(["dashboard"])),
    create: vi.fn(),
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

  await user.click(screen.getByLabelText(/^Switch view:/));
  await user.click(screen.getByRole("button", { name: "New view" }));

  expect(screen.queryByRole("group", { name: "From marimo-studio" })).not.toBeInTheDocument();
  expect(screen.getByRole("radio", { name: /HTML/ })).toBeChecked();
  controller.dispose();
});

it("groups starter choices by registering distribution", async () => {
  const remote: ViewRemote = {
    list: vi.fn(async () => viewList(["dashboard"], "dashboard", [componentStarter, starter])),
    create: vi.fn(),
    remove: vi.fn(),
  };
  const controller = new ViewController(
    "dashboard",
    ["dashboard"],
    remote,
    vi.fn(async () => true),
    vi.fn(async () => true),
    vi.fn(),
    [componentStarter, starter],
    starter.id,
  );
  const user = userEvent.setup();
  render(<ViewMenu controller={controller} />);

  await user.click(screen.getByLabelText(/^Switch view:/));
  await user.click(screen.getByRole("button", { name: "New view" }));

  const acme = screen.getByRole("group", { name: "From acme-views" });
  const studio = screen.getByRole("group", { name: "From marimo-studio" });
  expect(within(acme).getByRole("radio", { name: /Component project/ })).toBeInTheDocument();
  expect(within(studio).getByRole("radio", { name: /HTML/ })).toBeChecked();
  controller.dispose();
});
