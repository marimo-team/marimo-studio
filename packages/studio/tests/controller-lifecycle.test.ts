import { describe, expect, it, vi } from "vite-plus/test";

import type { ViewRemote } from "../src/features/views/remote.ts";

import { ViewController } from "../src/features/views/controller.ts";
import { starter, viewList } from "./fixtures.ts";

const deferred = <T>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
};

describe("feature controller lifecycle", () => {
  it("keeps the final available view out of the removal flow", async () => {
    const remote: ViewRemote = {
      list: vi.fn(async () => viewList(["dashboard"])),
      create: vi.fn(),
      remove: vi.fn(),
    };
    const controller = new ViewController(
      "dashboard",
      ["dashboard"],
      remote,
      vi.fn(async () => true),
      vi.fn(async () => true),
      vi.fn(),
    );

    controller.beginRemoval("dashboard");
    expect(await controller.deleteSelected()).toBe(false);
    expect(remote.remove).not.toHaveBeenCalled();
    expect(controller.getSnapshot()).toMatchObject({
      current: "dashboard",
      views: ["dashboard"],
    });
    expect(controller.getSnapshot().removing).toBeUndefined();
    controller.dispose();
  });

  it("ignores a delayed selection after a newer selection commits", async () => {
    const report = deferred<boolean>();
    const select = vi.fn((view: string) =>
      view === "report" ? report.promise : Promise.resolve(true),
    );
    const controller = new ViewController(
      "dashboard",
      ["dashboard", "report"],
      { list: vi.fn(), create: vi.fn(), remove: vi.fn() },
      select,
      vi.fn(async () => true),
      vi.fn(),
    );

    const older = controller.choose("report");
    expect(await controller.choose("dashboard")).toBe(true);
    report.resolve(true);

    expect(await older).toBe(false);
    expect(controller.getSnapshot().current).toBe("dashboard");
    controller.dispose();
  });

  it("applies shared canonical inventory when ensureAvailable misses its requested view", async () => {
    const listing = deferred<Awaited<ReturnType<ViewRemote["list"]>>>();
    const remote: ViewRemote = {
      list: vi.fn(() => listing.promise),
      create: vi.fn(),
      remove: vi.fn(),
    };
    const controller = new ViewController(
      "dashboard",
      ["dashboard"],
      remote,
      vi.fn(async () => true),
      vi.fn(async () => true),
      vi.fn(),
    );

    const refreshing = controller.refreshInventory();
    const ensuring = controller.ensureAvailable("missing");
    await Promise.resolve();
    expect(remote.list).toHaveBeenCalledOnce();
    listing.resolve(viewList(["dashboard", "report"]));

    await refreshing;
    expect(await ensuring).toBe(false);
    expect(controller.getSnapshot().views).toEqual(["dashboard", "report"]);
    controller.dispose();
  });

  it("keeps shared inventory alive when its first caller is superseded", async () => {
    const listing = deferred<Awaited<ReturnType<ViewRemote["list"]>>>();
    const remote: ViewRemote = {
      list: vi.fn((_signal?: AbortSignal) => listing.promise),
      create: vi.fn(),
      remove: vi.fn(),
    };
    const controller = new ViewController(
      "dashboard",
      ["dashboard"],
      remote,
      vi.fn(async () => true),
      vi.fn(async () => true),
      vi.fn(),
    );
    const older = new AbortController();
    const newer = new AbortController();

    const superseded = controller.ensureAvailable("report", older.signal);
    const current = controller.ensureAvailable("analysis", newer.signal);
    older.abort();
    await expect(superseded).rejects.toMatchObject({ name: "AbortError" });
    listing.resolve(viewList(["dashboard", "analysis"]));

    await expect(current).resolves.toBe(true);
    expect(remote.list).toHaveBeenCalledWith();
    expect(controller.getSnapshot().views).toEqual(["dashboard", "analysis"]);
    controller.dispose();
  });

  it("keeps create and delete mutations exclusive", async () => {
    const prepared = deferred<boolean>();
    const remote: ViewRemote = {
      list: vi.fn(async () => viewList(["dashboard", "report"])),
      create: vi.fn(async (name: string, _starter: string) => ({
        schema: 1 as const,
        name,
      })),
      remove: vi.fn(),
    };
    const controller = new ViewController(
      "dashboard",
      ["dashboard", "report"],
      remote,
      vi.fn(async () => true),
      vi.fn(() => prepared.promise),
      vi.fn(),
      [starter],
    );
    controller.beginRemoval("dashboard");

    const creating = controller.create("created", starter.id);
    const deleting = controller.deleteSelected();
    expect(remote.remove).not.toHaveBeenCalled();
    prepared.resolve(true);
    expect(await creating).toBe(true);
    expect(await deleting).toBe(false);
    controller.dispose();
  });

  it("cancels a pending selection before a failed create mutation", async () => {
    const selected = deferred<boolean>();
    const cancelSelection = vi.fn();
    const remote: ViewRemote = {
      list: vi.fn(async () => viewList(["dashboard", "report"])),
      create: vi.fn(async () => {
        throw new Error("create failed");
      }),
      remove: vi.fn(),
    };
    const controller = new ViewController(
      "dashboard",
      ["dashboard", "report"],
      remote,
      vi.fn(() => selected.promise),
      vi.fn(async () => true),
      cancelSelection,
      [starter],
      starter.id,
    );

    const choosing = controller.choose("report");
    expect(await controller.create("created", starter.id)).toBe(false);
    expect(cancelSelection).toHaveBeenCalledOnce();
    expect(controller.getSnapshot().current).toBe("dashboard");
    selected.resolve(true);
    expect(await choosing).toBe(false);
    expect(controller.getSnapshot().current).toBe("dashboard");
    controller.dispose();
  });

  it("retains the previous view after a created view commits", async () => {
    const release = vi.fn();
    const controller = new ViewController(
      "dashboard",
      ["dashboard"],
      {
        list: vi.fn(async () => viewList(["dashboard", "report"])),
        create: vi.fn(async (name: string, _starter: string) => ({
          schema: 1 as const,
          name,
        })),
        remove: vi.fn(),
      },
      vi.fn(async () => true),
      vi.fn(async () => true),
      vi.fn(),
      [starter],
      starter.id,
      vi.fn(async () => true),
      release,
    );

    await expect(controller.create("report", starter.id)).resolves.toBe(true);

    expect(controller.getSnapshot()).toMatchObject({
      current: "report",
      views: ["dashboard", "report"],
    });
    expect(release).not.toHaveBeenCalled();
    controller.dispose();
  });

  it("cancels a pending selection before removing a non-current view", async () => {
    const selected = deferred<boolean>();
    const cancelSelection = vi.fn();
    const order: string[] = [];
    const remote: ViewRemote = {
      list: vi.fn(async () => viewList(["dashboard"])),
      create: vi.fn(),
      remove: vi.fn(async (name: string) => {
        order.push(`remove:${name}`);
        return { ...viewList(["dashboard"]), name };
      }),
    };
    const controller = new ViewController(
      "dashboard",
      ["dashboard", "report"],
      remote,
      vi.fn(() => selected.promise),
      vi.fn(async () => true),
      cancelSelection,
      [starter],
      starter.id,
      vi.fn(async () => true),
      (view) => order.push(`release:${view}`),
    );

    const choosing = controller.choose("report");
    controller.beginRemoval("report");
    expect(await controller.deleteSelected()).toBe(true);
    expect(cancelSelection).toHaveBeenCalledOnce();
    selected.resolve(true);
    expect(await choosing).toBe(false);
    expect(controller.getSnapshot()).toMatchObject({
      current: "dashboard",
      views: ["dashboard"],
    });
    expect(order).toEqual(["release:report", "remove:report"]);
    controller.dispose();
  });

  it("keeps delete and create mutations exclusive", async () => {
    const prepared = deferred<boolean>();
    const remote: ViewRemote = {
      list: vi.fn(async () => viewList(["dashboard", "report"])),
      create: vi.fn(),
      remove: vi.fn(async (name: string) => ({
        ...viewList(["report"], "report"),
        name,
      })),
    };
    const controller = new ViewController(
      "dashboard",
      ["dashboard", "report"],
      remote,
      vi.fn(async () => true),
      vi.fn(() => prepared.promise),
      vi.fn(),
      [starter],
      starter.id,
      vi.fn(async () => true),
    );
    controller.beginRemoval("dashboard");

    const deleting = controller.deleteSelected();
    expect(await controller.create("created", starter.id)).toBe(false);
    expect(remote.create).not.toHaveBeenCalled();
    prepared.resolve(true);
    expect(await deleting).toBe(true);
    controller.dispose();
  });

  it("ignores an inventory read started before a successful create", async () => {
    const listing = deferred<Awaited<ReturnType<ViewRemote["list"]>>>();
    const canonical = viewList(["dashboard", "report"]);
    const remote: ViewRemote = {
      list: vi
        .fn()
        .mockImplementationOnce(() => listing.promise)
        .mockResolvedValue(canonical),
      create: vi.fn(async (name: string, _starter: string) => ({
        schema: 1 as const,
        name,
      })),
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
    );
    const refreshing = controller.refreshInventory();
    await Promise.resolve();

    expect(await controller.create("report", starter.id)).toBe(true);
    listing.resolve(viewList(["dashboard"]));
    await refreshing;

    expect(controller.getSnapshot().views).toEqual(["dashboard", "report"]);
    expect(controller.getSnapshot().current).toBe("report");
    controller.dispose();
  });

  it("uses a fresh inventory read when active removal supersedes a refresh", async () => {
    const stale = deferred<Awaited<ReturnType<ViewRemote["list"]>>>();
    const current = deferred<Awaited<ReturnType<ViewRemote["list"]>>>();
    const select = vi.fn(async () => true);
    const settle = vi.fn(async () => true);
    const remove = vi.fn(async (name: string) => ({
      ...viewList(["report"], "report"),
      name,
    }));
    const remote: ViewRemote = {
      list: vi
        .fn()
        .mockImplementationOnce(() => stale.promise)
        .mockImplementationOnce(() => current.promise)
        .mockResolvedValue(viewList(["report"], "report")),
      create: vi.fn(),
      remove,
    };
    const controller = new ViewController(
      "dashboard",
      ["dashboard", "report"],
      remote,
      select,
      vi.fn(async () => true),
      vi.fn(),
      [],
      "",
      settle,
    );
    const refreshing = controller.refreshInventory();
    await vi.waitFor(() => expect(remote.list).toHaveBeenCalledOnce());

    controller.beginRemoval("dashboard");
    const deleting = controller.deleteSelected();
    await vi.waitFor(() => expect(remote.list).toHaveBeenCalledTimes(2));
    stale.resolve(viewList(["dashboard"]));
    await refreshing;
    expect(controller.getSnapshot().views).toEqual(["dashboard", "report"]);

    const ensuring = controller.ensureAvailable("analysis");
    await Promise.resolve();
    expect(remote.list).toHaveBeenCalledTimes(2);
    current.resolve(viewList(["dashboard", "report", "analysis"]));

    await expect(ensuring).resolves.toBe(true);
    await expect(deleting).resolves.toBe(true);
    expect(select).toHaveBeenCalledWith("report", "develop");
    expect(settle).toHaveBeenCalledWith("report");
    expect(remove).toHaveBeenCalledWith("dashboard");
    expect(controller.getSnapshot()).toMatchObject({
      current: "report",
      views: ["report"],
    });
    expect(select).toHaveBeenCalledOnce();
    controller.dispose();
  });

  it("does not publish availability after inventory ownership changes during selection", async () => {
    const selected = deferred<boolean>();
    const release = vi.fn();
    const controller = new ViewController(
      "dashboard",
      ["dashboard"],
      {
        list: vi.fn(async () => viewList(["report"], "report")),
        create: vi.fn(),
        remove: vi.fn(),
      },
      vi.fn(() => selected.promise),
      vi.fn(async () => true),
      vi.fn(),
      [],
      "",
      vi.fn(async () => true),
      release,
    );

    const available = controller.ensureAvailable("report");
    await vi.waitFor(() => expect(controller.getSnapshot().selecting).toBe("report"));
    controller.dispose();
    selected.resolve(true);

    await expect(available).resolves.toBe(false);
    expect(release).not.toHaveBeenCalled();
  });

  it("does not select a view after a pending inventory read is disposed", async () => {
    const listing = deferred<Awaited<ReturnType<ViewRemote["list"]>>>();
    const select = vi.fn(async () => true);
    const remote: ViewRemote = {
      list: vi.fn(() => listing.promise),
      create: vi.fn(),
      remove: vi.fn(),
    };
    const controller = new ViewController(
      "dashboard",
      ["dashboard"],
      remote,
      select,
      vi.fn(async () => true),
      vi.fn(),
    );
    const refreshing = controller.refreshInventory();
    await Promise.resolve();

    controller.dispose();
    listing.resolve(viewList(["report"], "report"));
    await refreshing;

    expect(select).not.toHaveBeenCalled();
  });

  it("releases a non-current view removed by workspace inventory", async () => {
    const release = vi.fn();
    const controller = new ViewController(
      "dashboard",
      ["dashboard", "report"],
      {
        list: vi.fn(async () => viewList(["dashboard"])),
        create: vi.fn(),
        remove: vi.fn(),
      },
      vi.fn(async () => true),
      vi.fn(async () => true),
      vi.fn(),
      [],
      "",
      vi.fn(async () => true),
      release,
    );

    await controller.refreshInventory();

    expect(release).toHaveBeenCalledOnce();
    expect(release).toHaveBeenCalledWith("report");
    expect(controller.getSnapshot().current).toBe("dashboard");
    controller.dispose();
  });

  it("releases an externally removed current view after its successor commits", async () => {
    const selected = deferred<boolean>();
    const release = vi.fn();
    const controller = new ViewController(
      "dashboard",
      ["dashboard", "report"],
      {
        list: vi.fn(async () => viewList(["report"], "report")),
        create: vi.fn(),
        remove: vi.fn(),
      },
      vi.fn(() => selected.promise),
      vi.fn(async () => true),
      vi.fn(),
      [],
      "",
      vi.fn(async () => true),
      release,
    );

    const refreshing = controller.refreshInventory();
    await vi.waitFor(() => expect(controller.getSnapshot().selecting).toBe("report"));
    expect(release).not.toHaveBeenCalled();

    selected.resolve(true);
    await refreshing;

    expect(controller.getSnapshot().current).toBe("report");
    expect(release).toHaveBeenCalledOnce();
    expect(release).toHaveBeenCalledWith("dashboard");
    controller.dispose();
  });

  it("retargets the active view before deleting its files", async () => {
    const order: string[] = [];
    let removed = false;
    const remote: ViewRemote = {
      list: vi.fn(async () => {
        order.push("list");
        return removed ? viewList(["report"], "report") : viewList(["dashboard", "report"]);
      }),
      create: vi.fn(),
      remove: vi.fn(async (name: string) => {
        order.push(`remove:${name}`);
        removed = true;
        return { ...viewList(["report"], "report"), name };
      }),
    };
    const controller = new ViewController(
      "dashboard",
      ["dashboard", "report"],
      remote,
      vi.fn(async (view: string) => {
        order.push(`select:${view}`);
        return true;
      }),
      vi.fn(async () => {
        order.push("prepare");
        return true;
      }),
      vi.fn(),
      [],
      "",
      vi.fn(async (view: string) => {
        order.push(`settle:${view}`);
        return true;
      }),
      (view) => order.push(`release:${view}`),
    );

    controller.beginRemoval("dashboard");
    expect(await controller.deleteSelected()).toBe(true);

    expect(order.slice(0, 6)).toEqual([
      "prepare",
      "list",
      "select:report",
      "settle:report",
      "release:dashboard",
      "remove:dashboard",
    ]);
    expect(controller.getSnapshot().current).toBe("report");
    expect(controller.getSnapshot().views).toEqual(["report"]);
    controller.dispose();
  });

  it("keeps active files when the successor cannot be prepared", async () => {
    const remote: ViewRemote = {
      list: vi.fn(async () => viewList(["dashboard", "report"])),
      create: vi.fn(),
      remove: vi.fn(),
    };
    const controller = new ViewController(
      "dashboard",
      ["dashboard", "report"],
      remote,
      vi.fn(async () => false),
      vi.fn(async () => true),
      vi.fn(),
    );

    controller.beginRemoval("dashboard");
    expect(await controller.deleteSelected()).toBe(false);

    expect(remote.remove).not.toHaveBeenCalled();
    expect(controller.getSnapshot().current).toBe("dashboard");
    expect(controller.getSnapshot().removeError).toBe(
      "Select another page before removing this one.",
    );
    controller.dispose();
  });

  it("retains the current view when inventory removes it before its successor is ready", async () => {
    const select = vi.fn(async () => false);
    const remote: ViewRemote = {
      list: vi.fn(async () => viewList(["report"], "report")),
      create: vi.fn(),
      remove: vi.fn(),
    };
    const controller = new ViewController(
      "dashboard",
      ["dashboard", "report"],
      remote,
      select,
      vi.fn(async () => true),
      vi.fn(),
    );

    await controller.refreshInventory();

    expect(select).toHaveBeenCalledWith("report", "preserve");
    expect(controller.getSnapshot()).toMatchObject({
      current: "dashboard",
      views: ["report"],
    });
    controller.dispose();
  });

  it("recovers a concurrent inventory change through in-place selection", async () => {
    const select = vi.fn(async () => true);
    const remote: ViewRemote = {
      list: vi.fn(async () => viewList(["executive"], "executive")),
      create: vi.fn(),
      remove: vi.fn(async (name: string) => ({
        ...viewList(["executive"], "executive"),
        name,
      })),
    };
    const controller = new ViewController(
      "dashboard",
      ["dashboard", "report"],
      remote,
      select,
      vi.fn(async () => true),
      vi.fn(),
    );

    controller.beginRemoval("report");
    expect(await controller.deleteSelected()).toBe(true);

    expect(select).toHaveBeenCalledTimes(1);
    expect(select.mock.calls[0]?.slice(0, 2)).toEqual(["executive", "develop"]);
    expect(controller.getSnapshot().current).toBe("executive");
    controller.dispose();
  });
});
