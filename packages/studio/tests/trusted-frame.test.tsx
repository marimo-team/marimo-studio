import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vite-plus/test";

import { PreviewFrame, TrustedFrame } from "../src/features/workspace/TrustedFrame.tsx";

it("forwards the host's browser permissions", () => {
  render(
    <TrustedFrame
      allow="clipboard-read; clipboard-write"
      frameRef={vi.fn()}
      title="Trusted document"
    />,
  );
  expect(screen.getByTitle("Trusted document")).toHaveAttribute(
    "allow",
    "clipboard-read; clipboard-write",
  );
});

it("delegates fullscreen to an opaque preview document", () => {
  render(
    <PreviewFrame frameRef={vi.fn()} runtime="server" title="Presentation" view="dashboard" />,
  );
  const frame = screen.getByTitle("Presentation");
  expect(frame.getAttribute("allow")?.split(/;\s*/u)).toContain("fullscreen *");
  const sandbox = frame.getAttribute("sandbox")?.split(/\s+/u);
  expect(sandbox).toContain("allow-scripts");
  expect(sandbox).not.toContain("allow-same-origin");
});

it("keeps a visible preview inert until its runtime is ready", () => {
  const frameRef = vi.fn();
  const view = render(
    <PreviewFrame
      active
      frameRef={frameRef}
      interactive={false}
      runtime="server"
      title="dashboard custom view using server"
      view="dashboard"
    />,
  );
  const frame = screen.getByTitle("dashboard custom view using server");
  expect(frame).toHaveAttribute("inert");
  expect(frame).toHaveAttribute("aria-busy", "true");

  view.rerender(
    <PreviewFrame
      active
      frameRef={frameRef}
      interactive
      runtime="server"
      title="dashboard custom view using server"
      view="dashboard"
    />,
  );
  expect(frame).not.toHaveAttribute("inert");
  expect(frame).not.toHaveAttribute("aria-busy");
});
