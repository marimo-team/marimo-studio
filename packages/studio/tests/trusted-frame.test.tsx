import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vite-plus/test";

import { PreviewFrame, TrustedFrame } from "../src/features/workspace/TrustedFrame.tsx";
import { studioBootstrap } from "./studio-test-support.ts";

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

const policy = studioBootstrap.presentationFrame;

it("gives an opaque preview the bootstrap's frame policy", () => {
  render(
    <PreviewFrame
      frameRef={vi.fn()}
      policy={policy}
      runtime="server"
      title="Presentation"
      view="dashboard"
    />,
  );
  const frame = screen.getByTitle("Presentation");
  expect(frame).toHaveAttribute("sandbox", policy.sandbox);
  expect(frame).toHaveAttribute("allow", policy.allow);
  expect(frame.getAttribute("sandbox")?.split(/\s+/u)).not.toContain("allow-same-origin");
});

it("leaves a trusted server preview on the host origin", () => {
  render(
    <PreviewFrame
      frameRef={vi.fn()}
      policy={policy}
      runtime="server"
      sameOrigin
      title="Trusted presentation"
      view="dashboard"
    />,
  );

  expect(screen.getByTitle("Trusted presentation")).not.toHaveAttribute("sandbox");
});

it("keeps a visible preview inert until its runtime is ready", () => {
  const frameRef = vi.fn();
  const view = render(
    <PreviewFrame
      active
      frameRef={frameRef}
      policy={policy}
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
      policy={policy}
      interactive
      runtime="server"
      title="dashboard custom view using server"
      view="dashboard"
    />,
  );
  expect(frame).not.toHaveAttribute("inert");
  expect(frame).not.toHaveAttribute("aria-busy");
});
