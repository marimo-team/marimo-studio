import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vite-plus/test";

import { RuntimeMenu } from "../src/features/navigation/RuntimeMenu.tsx";
import { WorkspaceMenu } from "../src/features/navigation/WorkspaceMenu.tsx";
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

it("keeps the disclosure trigger keyboard-operable and restores its focus after Escape", async () => {
  const user = userEvent.setup();
  renderMenus();
  const trigger = screen.getByLabelText("Python preview runtime");
  const details = trigger.closest("details");

  await user.tab();
  expect(trigger).toHaveFocus();
  // jsdom omits the browser's Enter and Space toggling of a details summary.
  expect(details?.querySelector(":scope > summary")).toBe(trigger);
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
