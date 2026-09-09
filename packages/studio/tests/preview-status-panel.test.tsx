import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vite-plus/test";

import type { PreviewFrameState } from "../src/features/preview/controller.ts";

import { PreviewStatusPanel } from "../src/features/preview/PreviewStatusPanel.tsx";
import { RuntimeDiagnostics } from "../src/features/preview/runtime-diagnostics.ts";

const starting = (): PreviewFrameState => ({
  rendered: false,
  progress: null,
  url: "https://studio.test/views/report",
  lifecycleId: 1,
  status: { state: "loading", message: "Connecting to Python", diagnostics: [] },
  runtimeStatus: new RuntimeDiagnostics({ runtime: "server", view: "report" }).report(),
});

describe("preview preparation", () => {
  test("announces phase counts and retires them when the phase completes", () => {
    const state = starting();
    const onRetry = vi.fn();
    const { rerender } = render(<PreviewStatusPanel state={state} onRetry={onRetry} />);
    expect(screen.getByRole("progressbar", { name: "Connecting to Python" })).toBeVisible();

    rerender(
      <PreviewStatusPanel
        state={{
          ...state,
          progress: { message: "Capturing notebook states", completed: 2, total: 5 },
        }}
        onRetry={onRetry}
      />,
    );
    const progress = screen.getByRole("progressbar", { name: "Capturing notebook states" });
    expect(progress).toHaveAttribute("aria-valuenow", "2");
    expect(progress).toHaveAttribute("aria-valuemax", "5");
    expect(screen.getByText("2 of 5")).toBeVisible();

    rerender(
      <PreviewStatusPanel
        state={{ ...state, progress: { message: "Opening preview" } }}
        onRetry={onRetry}
      />,
    );
    expect(screen.getByRole("progressbar", { name: "Opening preview" })).not.toHaveAttribute(
      "aria-valuenow",
    );
    rerender(
      <PreviewStatusPanel
        state={{
          ...state,
          rendered: true,
          status: { state: "ready", message: "Live", diagnostics: [] },
        }}
        onRetry={onRetry}
      />,
    );
    expect(screen.queryByRole("status")).toBeNull();
  });

  test.each([false, true])("offers recovery after failure with rendered=%s", (rendered) => {
    const onRetry = vi.fn();
    render(
      <PreviewStatusPanel
        state={{
          ...starting(),
          rendered,
          status: {
            state: "error",
            message: "Needs repair",
            diagnostics: [
              {
                code: "runtime-failed",
                view: "report",
                scope: "runtime",
                severity: "error",
                message: "Notebook states could not be captured.",
                hint: "Check the notebook outputs, then retry.",
              },
            ],
          },
        }}
        onRetry={onRetry}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Notebook states could not be captured.");
    expect(screen.getByRole("alert")).toHaveTextContent("Check the notebook outputs, then retry.");
    fireEvent.click(screen.getByRole("button", { name: "Retry preview" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  test("shows the failure message when diagnostic details are unavailable", () => {
    render(
      <PreviewStatusPanel
        state={{
          ...starting(),
          status: { state: "error", message: "Connection closed", diagnostics: [] },
        }}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Connection closed");
    expect(screen.getByRole("button", { name: "Retry preview" })).toBeVisible();
  });

  test("copies the same structured diagnostic shown to readers", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const diagnostic = {
      code: "provider-input-invalid",
      view: "report",
      scope: "runtime",
      severity: "error" as const,
      message: "The provider could not read its input.",
      hint: "Correct the input path, then retry.",
      details: { provider: "example", input: { path: "data/records.csv" } },
    };
    try {
      render(
        <PreviewStatusPanel
          state={{
            ...starting(),
            status: { state: "error", message: "Needs repair", diagnostics: [diagnostic] },
          }}
          onRetry={vi.fn()}
        />,
      );
      fireEvent.click(screen.getByText("Technical details"));
      expect(screen.getByLabelText("Diagnostic details")).toHaveTextContent("data/records.csv");
      fireEvent.click(screen.getByRole("button", { name: "Copy diagnostic" }));
      await screen.findByText("Copied");
      expect(JSON.parse(writeText.mock.calls[0]?.[0])).toEqual(diagnostic);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
