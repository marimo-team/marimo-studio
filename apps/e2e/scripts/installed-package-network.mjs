import { z } from "zod";

export const INSTALLED_NETWORK_ENV = "MARIMO_STUDIO_E2E_INSTALLED_NETWORK";
export const INSTALLED_NETWORK_FILE_ENV = "MARIMO_STUDIO_E2E_INSTALLED_NETWORK_FILE";
const endpointSchema = z
  .object({
    origin: z.string().url(),
    port: z.number().int().positive().max(65535),
  })
  .strict()
  .refine(
    ({ origin, port }) => origin === `http://127.0.0.1:${port}`,
    "Expected owned loopback endpoint",
  );
const networkSchema = z
  .object({
    origin: z.string().url(),
    port: z.number().int().positive().max(65535),
    fresh: endpointSchema,
    static: endpointSchema,
    run: endpointSchema,
  })
  .strict();

export const createInstalledPackageNetwork = (endpoints) => {
  const endpoint = (value) => ({ origin: value.origin, port: value.port });
  return networkSchema.parse({
    ...endpoint(endpoints.edit),
    fresh: endpoint(endpoints.fresh),
    static: endpoint(endpoints.static),
    run: endpoint(endpoints.run),
  });
};

export const readInstalledPackageNetwork = () => {
  const encoded = process.env[INSTALLED_NETWORK_ENV];
  if (!encoded) throw new Error("Run installed acceptance through pnpm e2e:installed");
  const network = networkSchema.parse(JSON.parse(encoded));
  endpointSchema.parse({ origin: network.origin, port: network.port });
  return network;
};
