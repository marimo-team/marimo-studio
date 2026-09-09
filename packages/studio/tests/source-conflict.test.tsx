import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vite-plus/test";

import { SourceConflict } from "../src/features/source-editor/SourceConflict.tsx";

it.each([
  {
    kind: "read-only" as const,
    name: "deno.lock",
    local: "local lock",
    remote: "disk lock",
    revision: "r2",
    message: "deno.lock became read-only while you were editing.",
    diskLabel: "Saved version",
  },
  {
    kind: "unavailable" as const,
    name: "theme.css",
    local: "local style",
    remote: "saved style",
    revision: "r1",
    message: "theme.css is unavailable. Restore access to the file to save your edits.",
    diskLabel: "Last saved version",
  },
  {
    kind: "orphan" as const,
    name: "src/App.tsx",
    local: "local app",
    remote: "last disk app",
    revision: "r1",
    message: "src/App.tsx is no longer part of this view.",
    diskLabel: "Last saved version",
  },
])("shows discard recovery for a $kind conflict", async (scenario) => {
  const user = userEvent.setup();
  const discard = vi.fn();
  render(
    <SourceConflict
      name={scenario.name}
      conflict={{
        kind: scenario.kind,
        local: scenario.local,
        remote: { content: scenario.remote, revision: scenario.revision },
      }}
      onOverwriteSavedVersion={vi.fn()}
      onUseSavedVersion={discard}
    />,
  );

  expect(screen.getByRole("alert")).toHaveTextContent(scenario.message);
  expect(
    screen.queryByRole("button", { name: "Overwrite saved version with my edits" }),
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Compare" }));
  expect(screen.getByText(scenario.local)).toBeVisible();
  expect(screen.getByText(scenario.remote)).toBeVisible();
  expect(screen.getByText(scenario.diskLabel)).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Discard edits" }));
  expect(discard).toHaveBeenCalledOnce();
});

it("names both revision-conflict consequences", async () => {
  const user = userEvent.setup();
  const useSavedVersion = vi.fn();
  const overwriteSavedVersion = vi.fn();
  render(
    <SourceConflict
      name="src/App.tsx"
      conflict={{
        kind: "revision",
        local: "local app",
        remote: { content: "disk app", revision: "r2" },
        externalRecovery: "/workspace/.App.tsx.external-recovery",
      }}
      onOverwriteSavedVersion={overwriteSavedVersion}
      onUseSavedVersion={useSavedVersion}
    />,
  );

  expect(screen.getByRole("alert")).toHaveTextContent(
    "The previous saved version is preserved at /workspace/.App.tsx.external-recovery.",
  );
  await user.click(screen.getByRole("button", { name: "Use saved version" }));
  await user.click(screen.getByRole("button", { name: "Overwrite saved version with my edits" }));
  expect(useSavedVersion).toHaveBeenCalledOnce();
  expect(overwriteSavedVersion).toHaveBeenCalledOnce();
});
