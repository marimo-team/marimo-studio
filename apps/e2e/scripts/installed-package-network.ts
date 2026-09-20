import { z } from "zod";

export const INSTALLED_NETWORK_ENV = "MARIMO_STUDIO_E2E_INSTALLED_NETWORK";
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
const networkSchema = endpointSchema
  .safeExtend({
    fresh: endpointSchema,
    static: endpointSchema,
    run: endpointSchema,
  })
  .strict();

export type InstalledPackageNetwork = z.infer<typeof networkSchema>;

export const createInstalledPackageNetwork = (
  endpoints: Record<"edit" | "fresh" | "static" | "run", { origin: string; port: number }>,
) => {
  const endpoint = (value: { origin: string; port: number }) => ({
    origin: value.origin,
    port: value.port,
  });
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
  return networkSchema.parse(JSON.parse(encoded));
};
