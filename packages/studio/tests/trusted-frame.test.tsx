import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vite-plus/test";

import { PreviewFrame } from "../src/features/workspace/TrustedFrame.tsx";

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
