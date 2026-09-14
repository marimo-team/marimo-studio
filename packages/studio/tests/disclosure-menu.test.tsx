import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vite-plus/test";

import type { ViewRemote } from "../src/features/views/remote.ts";

import { RuntimeMenu } from "../src/features/navigation/RuntimeMenu.tsx";
import { WorkspaceMenu } from "../src/features/navigation/WorkspaceMenu.tsx";
import { ViewController } from "../src/features/views/controller.ts";
import { ViewMenu } from "../src/features/views/ViewMenu.tsx";
import { starter, viewList } from "./fixtures.ts";
import { studioBootstrap } from "./studio-test-support.ts";

const status = {
  diagnostics: [],
  message: "Live",
  state: "ready",
} as const;

const renderMenus = () => {
  const onWorkspaceAction = vi.fn();
  render(
    <>
      <RuntimeMenu
        current={studioBootstrap.runtimes[0]!}
        disabled={false}
        runtimes={studioBootstrap.runtimes}
        status={status}
        visible
        onSelect={vi.fn()}
      />
      <WorkspaceMenu
        arranging={false}
        mode="develop"
        previewUrl="/dashboard/"
        previewVisible={false}
        onModeSelect={vi.fn()}
        onWorkspaceAction={onWorkspaceAction}
      />
      <button type="button">Outside</button>
    </>,
  );
  return { onWorkspaceAction };
};

it("keeps native disclosure semantics and restores trigger focus after Escape", async () => {
  const user = userEvent.setup();
  renderMenus();
  const trigger = screen.getByLabelText("Python preview runtime");
  const details = trigger.closest("details");

  expect(trigger.tagName).toBe("SUMMARY");
  expect(details).toBeInstanceOf(HTMLDetailsElement);
  await user.click(trigger);
  const option = screen.getByRole("button", { name: /Browser/ });
  option.focus();
  await user.keyboard("{Escape}");

  await vi.waitFor(() => expect(trigger).toHaveFocus());
  expect(details?.open).toBe(false);
});

it("light-dismisses outside and keeps one disclosure menu open at a time", async () => {
  const user = userEvent.setup();
  renderMenus();
  const runtimeTrigger = screen.getByLabelText("Python preview runtime");
  const workspaceTrigger = screen.getByLabelText("Workspace options");
  const runtimeMenu = runtimeTrigger.closest("details");
  const workspaceMenu = workspaceTrigger.closest("details");

  await user.click(runtimeTrigger);
  expect(runtimeMenu?.open).toBe(true);
  await user.click(workspaceTrigger);
  expect(runtimeMenu?.open).toBe(false);
  expect(workspaceMenu?.open).toBe(true);

  const outside = screen.getByRole("button", { name: "Outside" });
  await user.click(outside);
  expect(workspaceMenu?.open).toBe(false);
  expect(outside).toHaveFocus();
});

it("keeps a busy view menu open when a peer requests ownership", async () => {
  const create = new Promise<Awaited<ReturnType<ViewRemote["create"]>>>(() => undefined);
  const remote: ViewRemote = {
    list: vi.fn(async () => viewList(["dashboard"])),
    create: vi.fn(() => create),
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
  render(
    <div id="marimo-studio-root">
      <ViewMenu controller={controller} />
      <RuntimeMenu
        current={studioBootstrap.runtimes[0]!}
        disabled={false}
        runtimes={studioBootstrap.runtimes}
        status={status}
        visible
        onSelect={vi.fn()}
      />
    </div>,
  );
  const viewTrigger = screen.getByLabelText(/^Switch view:/);
  const runtimeTrigger = screen.getByLabelText("Python preview runtime");
  const viewMenu = viewTrigger.closest("details");
  const runtimeMenu = runtimeTrigger.closest("details");

  await user.click(viewTrigger);
  await user.click(screen.getByRole("button", { name: "New view" }));
  await user.type(screen.getByLabelText("New view"), "created");
  await user.click(screen.getByRole("button", { name: "Create" }));
  expect(await screen.findByRole("button", { name: "Creating…" })).toBeDisabled();

  await user.click(runtimeTrigger);

  expect(viewMenu?.open).toBe(true);
  expect(runtimeMenu?.open).toBe(false);
  controller.dispose();
});

it("restores trigger focus when a menu action closes its disclosure", async () => {
  const user = userEvent.setup();
  const { onWorkspaceAction } = renderMenus();
  const trigger = screen.getByLabelText("Workspace options");

  await user.click(trigger);
  await user.click(screen.getByRole("button", { name: "Restore workspace" }));

  expect(onWorkspaceAction).toHaveBeenCalledWith("reset");
  await vi.waitFor(() => expect(trigger).toHaveFocus());
  expect(trigger.closest("details")?.open).toBe(false);
});
