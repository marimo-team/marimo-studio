import { expect, test, vi } from "vite-plus/test";

import { reconcileProjectedOutputState } from "../src/projected-output-state";

const owner = "__marimo_studio_output_owner";
const output = (resetUiObjectIds: string[] = []) => ({
  ownerCellId: owner,
  mimetype: "text/html",
  data: '<img src="/@file/current.png">',
  timestamp: 1,
  resetUiObjectIds,
});

test("replaces named UI generations while retaining cached output state", () => {
  const fresh = `${owner}-0`;
  const cached = `${owner}-1`;
  const entries = new Map([
    [fresh, {}],
    [cached, {}],
  ]);
  const resetVirtualFiles = vi.fn();
  const trackVirtualFiles = vi.fn();

  reconcileProjectedOutputState(output([fresh]), entries, resetVirtualFiles, trackVirtualFiles);

  expect(entries.has(fresh)).toBe(false);
  expect(entries.has(cached)).toBe(true);
  expect(resetVirtualFiles).toHaveBeenCalledWith(owner);
  expect(trackVirtualFiles).toHaveBeenCalledWith({
    cell_id: owner,
    output: {
      channel: "output",
      mimetype: "text/html",
      data: '<img src="/@file/current.png">',
      timestamp: 1,
    },
  });

  resetVirtualFiles.mockClear();
  trackVirtualFiles.mockClear();
  reconcileProjectedOutputState(output(), entries, resetVirtualFiles, trackVirtualFiles);

  expect(entries.has(cached)).toBe(true);
  expect(resetVirtualFiles).toHaveBeenCalledOnce();
  expect(trackVirtualFiles).toHaveBeenCalledOnce();
});

test("rejects a reset owned by a notebook cell before changing state", () => {
  const foreign = "source-cell-0";
  const entries = new Map([[foreign, {}]]);
  const resetVirtualFiles = vi.fn();
  const trackVirtualFiles = vi.fn();

  expect(() =>
    reconcileProjectedOutputState(output([foreign]), entries, resetVirtualFiles, trackVirtualFiles),
  ).toThrow("may reset only UI objects owned by its projection");
  expect(entries.has(foreign)).toBe(true);
  expect(resetVirtualFiles).not.toHaveBeenCalled();
  expect(trackVirtualFiles).not.toHaveBeenCalled();
});
