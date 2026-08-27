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
    diskLabel: "On disk",
  },
  {
    kind: "orphan" as const,
    name: "src/App.tsx",
    local: "local app",
    remote: "last disk app",
    revision: "r1",
    message: "src/App.tsx is no longer part of this view.",
    diskLabel: "Last on disk",
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
      onKeepLocal={vi.fn()}
      onUseDisk={discard}
    />,
  );

  expect(screen.getByRole("alert")).toHaveTextContent(scenario.message);
  expect(screen.queryByRole("button", { name: "Keep mine" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Compare" }));
  expect(screen.getByText(scenario.local)).toBeVisible();
  expect(screen.getByText(scenario.remote)).toBeVisible();
  expect(screen.getByText(scenario.diskLabel)).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Discard edits" }));
  expect(discard).toHaveBeenCalledOnce();
});

it("shows the preserved source path for a revision conflict", () => {
  render(
    <SourceConflict
      name="src/App.tsx"
      conflict={{
        kind: "revision",
        local: "local app",
        remote: { content: "disk app", revision: "r2" },
        externalRecovery: "/workspace/.App.tsx.external-recovery",
      }}
      onKeepLocal={vi.fn()}
      onUseDisk={vi.fn()}
    />,
  );

  expect(screen.getByRole("alert")).toHaveTextContent(
    "Previous disk content is preserved at /workspace/.App.tsx.external-recovery.",
  );
});
