import { expect, it, vi } from "vite-plus/test";

import { StarterCatalogController } from "../src/features/views/catalog.ts";
import { starter, viewGeneration, viewList } from "./fixtures.ts";

it("retains the generation for the current starter inventory", async () => {
  const hostGeneration = viewGeneration(4);
  const loaded = {
    ...viewList([], "dashboard", [starter]),
    generation: viewGeneration(5),
  };
  const accepted = {
    ...loaded,
    generation: viewGeneration(6),
  };
  const controller = new StarterCatalogController(
    vi.fn(async () => loaded),
    [],
    "",
    hostGeneration,
  );

  expect(controller.getSnapshot().generation).toBe(hostGeneration);

  await controller.refresh();
  expect(controller.getSnapshot().generation).toBe(loaded.generation);

  controller.accept(accepted);
  expect(controller.getSnapshot().generation).toBe(accepted.generation);
  controller.dispose();
});
