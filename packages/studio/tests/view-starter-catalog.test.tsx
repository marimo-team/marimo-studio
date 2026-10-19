import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vite-plus/test";

import type { ViewRemote } from "../src/features/views/remote.ts";

import { ViewController } from "../src/features/views/controller.ts";
import { ViewMenu } from "../src/features/views/ViewMenu.tsx";
import { STARTER_PREVIEW_URL, componentStarter, starter, viewList } from "./fixtures.ts";

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
  render(<ViewMenu controller={controller} starterPreview={STARTER_PREVIEW_URL} />);

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

it("shows an unavailable starter's recovery and keeps Create disabled", async () => {
  const unavailable = {
    ...componentStarter,
    documents: ["src/App.tsx", "src/theme.css"],
    requirement: "Deno 2.9+",
    availability: {
      available: false,
      version: null,
      reason: "Deno is unavailable.",
      action: "Install Deno with `pixi global install deno`.",
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
  render(<ViewMenu controller={controller} starterPreview={STARTER_PREVIEW_URL} />);

  await user.click(screen.getByLabelText(/^Switch view:/));
  await user.click(screen.getByRole("button", { name: "New view" }));
  const option = screen.getByRole("radio", { name: /Component project/ });
  expect(option.closest("label")).toHaveTextContent("Needs Deno 2.9+");
  await user.click(option);

  const details = screen.getByRole("region", { name: "Component project" });
  expect(details).toHaveTextContent("Deno is unavailable.");
  expect(within(details).getByText("pixi global install deno").tagName).toBe("CODE");
  expect(details).toHaveTextContent("src/App.tsx");
  expect(screen.getByRole("button", { name: "Create view" })).toBeDisabled();
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
  render(<ViewMenu controller={controller} starterPreview={STARTER_PREVIEW_URL} />);

  await user.click(screen.getByLabelText(/^Switch view:/));
  await user.click(screen.getByRole("button", { name: "New view" }));

  const acme = screen.getByRole("group", { name: "acme-views" });
  const studio = screen.getByRole("group", { name: "marimo-studio" });
  expect(within(acme).getByRole("radio", { name: /Component project/ })).toBeInTheDocument();
  expect(within(studio).getByRole("radio", { name: /HTML/ })).toBeChecked();
  controller.dispose();
});

it("shows the folder where a new view's files are created", async () => {
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
  );
  const user = userEvent.setup();
  render(<ViewMenu controller={controller} starterPreview={STARTER_PREVIEW_URL} />);

  await user.click(screen.getByLabelText(/^Switch view:/));
  await user.click(screen.getByRole("button", { name: "New view" }));
  await screen.findByRole("radio", { name: /HTML/ });
  await user.type(screen.getByLabelText("Name"), "Briefing");
  expect(screen.getByText("studio/analysis/…/")).toBeVisible();
  await user.clear(screen.getByLabelText("Name"));
  await user.type(screen.getByLabelText("Name"), "briefing");

  expect(screen.getByText("studio/analysis/briefing/")).toBeVisible();
  controller.dispose();
});

it.each([
  ["source", true],
  ["none", true],
  ["workspace", false],
  [null, false],
] as const)("describes Create with what a %s hub session keeps", async (persistence, warns) => {
  const remote: ViewRemote = {
    list: vi.fn(async () => ({ ...viewList(["dashboard"]), persistence })),
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
  render(<ViewMenu controller={controller} starterPreview={STARTER_PREVIEW_URL} />);

  await user.click(screen.getByLabelText(/^Switch view:/));
  await user.click(screen.getByRole("button", { name: "New view" }));
  await screen.findByRole("radio", { name: /HTML/ });

  const create = screen.getByRole("button", { name: "Create view" });
  expect(create).toHaveAccessibleDescription(warns ? expect.stringMatching(/\bsession\b/iu) : "");
  controller.dispose();
});
