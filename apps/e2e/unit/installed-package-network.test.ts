import { afterEach, expect, test, vi } from "vite-plus/test";

import {
  createInstalledPackageNetwork,
  INSTALLED_NETWORK_ENV,
  readInstalledPackageNetwork,
} from "../scripts/installed-package-network.ts";

const endpoint = { origin: "http://127.0.0.1:42001", port: 42001 };
const endpoints = { edit: endpoint, fresh: endpoint, static: endpoint, run: endpoint };

afterEach(() => vi.unstubAllEnvs());

test("validates the edit and nested endpoints at publication and consumption", () => {
  const network = createInstalledPackageNetwork(endpoints);
  vi.stubEnv(INSTALLED_NETWORK_ENV, JSON.stringify(network));
  expect(readInstalledPackageNetwork()).toEqual(network);
  for (const name of ["edit", "fresh"] as const) {
    const mismatched = { ...endpoint, port: 42002 };
    expect(() => createInstalledPackageNetwork({ ...endpoints, [name]: mismatched })).toThrow(
      "Expected owned loopback endpoint",
    );
    const invalid =
      name === "edit" ? { ...network, ...mismatched } : { ...network, fresh: mismatched };
    vi.stubEnv(INSTALLED_NETWORK_ENV, JSON.stringify(invalid));
    expect(() => readInstalledPackageNetwork()).toThrow("Expected owned loopback endpoint");
  }
});
