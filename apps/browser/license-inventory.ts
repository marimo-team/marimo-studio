import type { Plugin } from "vite";

import { readMarimoSource } from "@marimo-studio/marimo-frontend/build-metadata";
import { createHash } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod";

import { browserLicenseFallbackFor, browserLicenseFallbacks } from "./license-fallbacks.ts";

const contactObjectSchema = z
  .object({
    email: z.string().optional(),
    name: z.string().optional(),
    url: z.string().optional(),
  })
  .passthrough();
const repositoryObjectSchema = z
  .object({ directory: z.string().optional(), url: z.string() })
  .passthrough();
const licenseObjectSchema = z.object({ type: z.string() }).passthrough();
const contactSchema = z.union([z.string(), contactObjectSchema]);
const packageManifestSchema = z
  .object({
    author: contactSchema.optional(),
    license: z.union([z.string(), licenseObjectSchema]).optional(),
    name: z.string().min(1),
    private: z.boolean().optional(),
    repository: z.union([z.string(), repositoryObjectSchema]).optional(),
    version: z.string().min(1),
  })
  .passthrough();
const packageIdentitySchema = packageManifestSchema.pick({ name: true, version: true });
type Manifest = z.infer<typeof packageManifestSchema>;

type LicenseFile = {
  name: string;
  sha256: string;
  source: string;
  text: string;
};

type PackageRecord = {
  author?: string;
  files: LicenseFile[];
  license: string;
  name: string;
  repository?: string;
  root: string;
  version: string;
};

type JsonPackageRecord = {
  author?: string;
  files: { name: string; sha256: string; source: string }[];
  license: string;
  name: string;
  repository?: string;
  version: string;
};

type Bundle = Record<
  string,
  | {
      modules: Record<
        string,
        { code: string | null; renderedExports: string[]; renderedLength: number }
      >;
      type: "chunk";
    }
  | { type: "asset" }
>;

type InventoryContext = {
  emitFile(file: { fileName: string; source: string | Uint8Array; type: "asset" }): string;
};

const requireFromVite = createRequire(import.meta.resolve("vite/package.json"));
const packageRoot = dirname(fileURLToPath(import.meta.url));
const workspaceRoot = resolve(packageRoot, "../..");
const fallbackTextRoot = join(packageRoot, "license-texts");
const viteManifest = requireFromVite.resolve("@voidzero-dev/vite-plus-core/package.json");
const licenseName = /^(?:licen[cs]es?|copying|notice|third[-_. ]?party)(?:$|[-_. ].*)/i;
const licenseTextName = /^(?:licen[cs]es?|copying)(?:$|[-_. ].*)/i;
const sourceLicenseFile = /\.(?:[cm]?[jt]sx?|py|rb|sh|bash|zsh|fish|ps1)$/i;
const supportedLicenseExpressions = new Set([
  "(Apache-2.0 AND BSD-3-Clause)",
  "(MPL-2.0 OR Apache-2.0)",
  "0BSD",
  "Apache-2.0",
  "BSD-2-Clause",
  "BSD-3-Clause",
  "ISC",
  "MIT",
  "MPL-2.0",
  "Unlicense",
]);
const licenseOverrides = new Map([
  ["khroma@2.1.0", "MIT"],
  ["react-vega@8.0.0", "BSD-3-Clause"],
]);
const sha256 = (source: Uint8Array) => createHash("sha256").update(source).digest("hex");
const compare = (left: string, right: string) => {
  if (left < right) {
    return -1;
  }
  if (left > right) {
    return 1;
  }
  return 0;
};

const readManifest = async (path: string): Promise<Manifest> => {
  let source: string;
  try {
    source = await readFile(path, "utf8");
  } catch (error: unknown) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") {
      throw error;
    }
    throw new Error(`Cannot read package manifest ${path}`, { cause: error });
  }
  try {
    return packageManifestSchema.parse(JSON.parse(source));
  } catch (error: unknown) {
    throw new Error(`Cannot parse package manifest ${path}`, { cause: error });
  }
};

const licenseExpression = (value: Manifest["license"], path: string, coordinate: string) => {
  let expression = "";
  const stringValue = z.string().safeParse(value);
  if (stringValue.success) {
    expression = stringValue.data.trim();
  } else {
    const objectValue = licenseObjectSchema.safeParse(value);
    if (objectValue.success) {
      expression = objectValue.data.type.trim();
    }
  }
  if (!supportedLicenseExpressions.has(expression)) {
    const override = licenseOverrides.get(coordinate);
    if (override) {
      return override;
    }
    throw new Error(`Package manifest ${path} has unknown licensing`);
  }
  return expression;
};

const manifestContact = (value: Manifest["author"]) => {
  const stringValue = z.string().safeParse(value);
  if (stringValue.success) {
    return stringValue.data.trim();
  }
  const objectValue = contactObjectSchema.safeParse(value);
  if (!objectValue.success) {
    return undefined;
  }
  const fields = [objectValue.data.name, objectValue.data.email, objectValue.data.url]
    .map((field) => field?.trim() ?? "")
    .filter(Boolean);
  return fields.length > 0 ? fields.join(" | ") : undefined;
};

const repositoryUrl = (value: Manifest["repository"]) => {
  const stringValue = z.string().safeParse(value);
  if (stringValue.success) {
    return stringValue.data.trim();
  }
  const objectValue = repositoryObjectSchema.safeParse(value);
  if (!objectValue.success) {
    return undefined;
  }
  const url = objectValue.data.url.trim();
  const directory = objectValue.data.directory?.trim() ?? "";
  return url && directory ? `${url}#${directory}` : url || undefined;
};

const readLicenseFile = async (path: string, name: string, source: string) => {
  let bytes: Uint8Array;
  try {
    bytes = await readFile(path);
  } catch (error: unknown) {
    throw new Error(`Cannot read license file ${path}`, { cause: error });
  }
  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch (error: unknown) {
    throw new Error(`License file ${path} is not UTF-8 text`, { cause: error });
  }
  if (!text.trim()) {
    throw new Error(`License file ${path} is empty`);
  }
  return { name, sha256: sha256(bytes), source, text } satisfies LicenseFile;
};

const rootLicenseFiles = async (root: string, source: string) => {
  let names: string[];
  try {
    names = (await readdir(root))
      .filter((name) => licenseName.test(name) && !sourceLicenseFile.test(name))
      .sort();
  } catch (error: unknown) {
    throw new Error(`Cannot inspect package licenses in ${root}`, { cause: error });
  }
  return Promise.all(names.map((name) => readLicenseFile(join(root, name), name, source)));
};

const packageRecord = async (manifestPath: string): Promise<PackageRecord> => {
  const manifest = await readManifest(manifestPath);
  const name = manifest.name.trim();
  const version = manifest.version.trim();
  const root = dirname(manifestPath);
  return {
    author: manifestContact(manifest.author),
    files: await rootLicenseFiles(root, `${name}@${version}`),
    license: licenseExpression(manifest.license, manifestPath, `${name}@${version}`),
    name,
    repository: repositoryUrl(manifest.repository),
    root,
    version,
  };
};

const cleanModuleId = (id: string) => {
  const withoutNull = id.startsWith("\0") ? id.slice(1) : id;
  const withoutQuery = withoutNull.split("?", 1)[0];
  return withoutQuery.startsWith("file:") ? fileURLToPath(withoutQuery) : withoutQuery;
};

const nearestManifest = async (id: string) => {
  let directory = dirname(id);
  while (directory !== dirname(directory)) {
    const candidate = join(directory, "package.json");
    try {
      const source = await readFile(candidate, "utf8");
      if (packageIdentitySchema.safeParse(JSON.parse(source)).success) {
        return candidate;
      }
    } catch (error: unknown) {
      if (!(error instanceof Error && "code" in error && error.code === "ENOENT")) {
        throw error;
      }
    }
    directory = dirname(directory);
  }
  throw new Error(`Cannot find a package manifest for bundled module ${id}`);
};

const installedManifest = async (id: string) => {
  const normalized = id.replaceAll("\\", "/");
  const marker = "/node_modules/";
  const markerIndex = normalized.lastIndexOf(marker);
  if (markerIndex < 0) {
    return undefined;
  }
  const packagePath = normalized.slice(markerIndex + marker.length).split("/");
  if (!packagePath[0]) {
    throw new Error(`Cannot resolve installed package for bundled module ${id}`);
  }
  const packageParts = packagePath[0]?.startsWith("@") ? 2 : 1;
  if (packagePath.length < packageParts) {
    throw new Error(`Cannot resolve installed package for bundled module ${id}`);
  }
  const root = `${normalized.slice(0, markerIndex + marker.length)}${packagePath
    .slice(0, packageParts)
    .join("/")}`;
  const manifest = join(root, "package.json");
  await readManifest(manifest);
  return manifest;
};

const within = (parent: string, child: string) => {
  const path = relative(parent, child);
  return path === "" || (!path.startsWith("..") && !isAbsolute(path));
};

const collectModuleIds = (bundle: Bundle, target: Set<string>) => {
  for (const output of Object.values(bundle)) {
    if (output.type !== "chunk") {
      continue;
    }
    for (const id of Object.keys(output.modules)) {
      target.add(id);
    }
  }
};

const mergeRecord = (records: Map<string, PackageRecord>, next: PackageRecord) => {
  const key = `${next.name}@${next.version}`;
  const current = records.get(key);
  if (!current) {
    records.set(key, next);
    return;
  }
  if (
    current.license !== next.license ||
    current.repository !== next.repository ||
    current.author !== next.author
  ) {
    throw new Error(`Conflicting package metadata for ${key}`);
  }
  const files = new Map(current.files.map((file) => [file.name, file]));
  for (const file of next.files) {
    const existing = files.get(file.name);
    if (existing && existing.sha256 !== file.sha256) {
      throw new Error(`Conflicting license file ${file.name} for ${key}`);
    }
    files.set(file.name, file);
  }
  current.files = [...files.values()].sort((left, right) =>
    compare(`${left.name}:${left.sha256}`, `${right.name}:${right.sha256}`),
  );
};

const packageManifests = async (moduleIds: Set<string>, marimoRoot: string) => {
  const manifests = new Set<string>();
  for (const rawId of moduleIds) {
    const id = cleanModuleId(rawId);
    if (isAbsolute(id)) {
      const installed = await installedManifest(id);
      if (installed) {
        manifests.add(installed);
        continue;
      }
      if (within(marimoRoot, id) || within(workspaceRoot, id)) {
        continue;
      }
      manifests.add(await nearestManifest(id));
      continue;
    }
    const virtualId = rawId.startsWith("\0") ? rawId.slice(1) : "";
    const generatedPackage = /^(@[^@/]+|[^@/]+)@([^/]+)\//.exec(virtualId);
    if (generatedPackage) {
      const name = generatedPackage[1].startsWith("@")
        ? generatedPackage[1].replace("+", "/")
        : generatedPackage[1];
      const manifest = requireFromVite.resolve(`${name}/package.json`);
      const metadata = await readManifest(manifest);
      if (metadata.name !== name || metadata.version !== generatedPackage[2]) {
        throw new Error(`Generated module ${rawId} resolved to a different package`);
      }
      manifests.add(manifest);
      continue;
    }
    if (
      rawId === "\0rolldown/runtime.js" ||
      rawId === "\0vite/preload-helper.js" ||
      rawId === "__vite-browser-external"
    ) {
      manifests.add(viteManifest);
      continue;
    }
    throw new Error(`No license owner for bundled virtual module ${JSON.stringify(rawId)}`);
  }
  return manifests;
};

const marimoRecord = async (root: string, version: string, repository: string) => {
  const files = [await readLicenseFile(join(root, "LICENSE"), "LICENSE", `marimo@${version}`)];
  return {
    files,
    license: "Apache-2.0",
    name: "marimo",
    repository,
    root,
    version,
  } satisfies PackageRecord;
};

const applyReviewedFallbacks = async (records: PackageRecord[]) => {
  const used = new Set<string>();
  for (const record of records) {
    if (record.files.some((file) => licenseTextName.test(file.name))) {
      continue;
    }
    const coordinate = `${record.name}@${record.version}`;
    const fallback = browserLicenseFallbackFor(coordinate);
    if (!fallback) {
      throw new Error(`${coordinate} has no packaged or reviewed license text`);
    }
    if (fallback.license !== record.license) {
      throw new Error(
        `${coordinate} declares ${record.license}, but its reviewed fallback is ${fallback.license}`,
      );
    }
    if (fallback.author && record.author && fallback.author !== record.author) {
      throw new Error(`${coordinate} has conflicting fallback author metadata`);
    }
    record.author ??= fallback.author;
    record.files.push(
      ...(await Promise.all(
        fallback.files.map(async (file) => {
          if (!/^[0-9a-f]{64}$/.test(file.sha256)) {
            throw new Error(`${coordinate} fallback has an invalid digest`);
          }
          const path = join(fallbackTextRoot, `${file.sha256}.txt`);
          let bytes: Uint8Array;
          try {
            bytes = await readFile(path);
          } catch (error: unknown) {
            throw new Error(`${coordinate} fallback text is unavailable: ${path}`, {
              cause: error,
            });
          }
          let text: string;
          try {
            text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
          } catch (error: unknown) {
            throw new Error(`${coordinate} fallback text is not UTF-8: ${path}`, {
              cause: error,
            });
          }
          if (!text.trim()) {
            throw new Error(`${coordinate} fallback text is empty: ${path}`);
          }
          const digest = sha256(bytes);
          if (digest !== file.sha256) {
            throw new Error(`${coordinate} fallback digest changed for ${file.name}`);
          }
          return {
            name: file.name,
            sha256: digest,
            source: file.provenance.url,
            text,
          };
        }),
      )),
    );
    used.add(coordinate);
  }
  const stale = [...browserLicenseFallbacks.keys()].filter((coordinate) => !used.has(coordinate));
  if (stale.length > 0) {
    throw new Error(`Browser license fallbacks are stale: ${stale.join(", ")}`);
  }
  const expectedAssets = [
    ...new Set(
      [...browserLicenseFallbacks.values()].flatMap((fallback) =>
        fallback.files.map((file) => `${file.sha256}.txt`),
      ),
    ),
  ].sort();
  const actualAssets = (await readdir(fallbackTextRoot))
    .filter((name) => name.endsWith(".txt"))
    .sort();
  if (actualAssets.join("\n") !== expectedAssets.join("\n")) {
    throw new Error("Browser license fallback assets differ from their manifest");
  }
};

const textInventory = (records: PackageRecord[]) => {
  const lines = [
    "Third-Party Notices",
    "",
    "The Marimo Studio browser distribution includes the packages listed below.",
    "Each license text is identified by its SHA-256 digest.",
    "",
  ];
  for (const record of records) {
    lines.push(`${record.name}@${record.version}`, `License: ${record.license}`);
    if (record.repository) {
      lines.push(`Repository: ${record.repository}`);
    }
    if (record.author) {
      lines.push(`Author: ${record.author}`);
    }
    for (const file of record.files) {
      lines.push(`License text: ${file.sha256} (${file.name}, ${file.source})`);
    }
    lines.push("");
  }
  return `${lines.join("\n")}\n`;
};

const licenseInventory = (records: PackageRecord[]) => {
  const bodies = new Map<string, { packages: Set<string>; sources: Set<string>; text: string }>();
  for (const record of records) {
    const coordinate = `${record.name}@${record.version}`;
    for (const file of record.files) {
      const current = bodies.get(file.sha256) ?? {
        packages: new Set<string>(),
        sources: new Set<string>(),
        text: file.text,
      };
      if (current.text !== file.text) {
        throw new Error(`License digest collision for ${file.sha256}`);
      }
      current.packages.add(coordinate);
      current.sources.add(
        file.source.startsWith("https://") ? file.source : `${file.source}/${file.name}`,
      );
      bodies.set(file.sha256, current);
    }
  }
  return [...bodies]
    .sort(([left], [right]) => compare(left, right))
    .map(([digest, body]) => ({
      packages: [...body.packages].sort(),
      sha256: digest,
      sources: [...body.sources].sort(),
      text: body.text,
    }));
};

const licenseText = (licenses: ReturnType<typeof licenseInventory>) => {
  const lines = ["Third-Party License Texts", ""];
  for (const license of licenses) {
    lines.push(
      `================================================================================`,
      `SHA-256: ${license.sha256}`,
      `Packages: ${license.packages.join(", ")}`,
      `Sources: ${license.sources.join(", ")}`,
      `================================================================================`,
      "",
      license.text.replace(/\s+$/, ""),
      "",
    );
  }
  return `${lines.join("\n")}\n`;
};

const jsonPackageRecord = ({
  author,
  files,
  license,
  name,
  repository,
  version,
}: PackageRecord) => {
  const record: JsonPackageRecord = {
    files: files
      .map(({ name: fileName, sha256: digest, source }) => ({
        name: fileName,
        sha256: digest,
        source,
      }))
      .sort((left, right) =>
        compare(`${left.name}:${left.sha256}`, `${right.name}:${right.sha256}`),
      ),
    license,
    name,
    version,
  };
  if (author) {
    record.author = author;
  }
  if (repository) {
    record.repository = repository;
  }
  return record;
};

const emitInventory = async (context: InventoryContext, moduleIds: Set<string>) => {
  const marimo = await readMarimoSource();
  const manifests = await packageManifests(moduleIds, marimo.path);
  const records = new Map<string, PackageRecord>();
  mergeRecord(records, await marimoRecord(marimo.path, marimo.version, marimo.repository));
  const packageErrors: string[] = [];
  for (const manifest of [...manifests].sort()) {
    try {
      mergeRecord(records, await packageRecord(manifest));
    } catch (error: unknown) {
      packageErrors.push(error instanceof Error ? error.message : String(error));
    }
  }
  if (packageErrors.length > 0) {
    throw new Error(`Cannot inventory browser packages:\n${packageErrors.join("\n")}`);
  }
  const packages = [...records.values()].sort((left, right) =>
    compare(`${left.name}@${left.version}`, `${right.name}@${right.version}`),
  );
  await applyReviewedFallbacks(packages);
  const licenses = licenseInventory(packages);
  const json = {
    schemaVersion: 1,
    marimo: {
      commit: marimo.commit,
      repository: marimo.repository,
      version: marimo.version,
    },
    packages: packages.map(jsonPackageRecord),
    licenseTexts: licenses.map(({ packages: owners, sha256: digest, sources }) => ({
      packages: owners,
      sha256: digest,
      sources,
    })),
  };
  const marimoLicense = await readFile(join(marimo.path, "LICENSE"));
  const studioLicense = await readFile(join(workspaceRoot, "packages", "marimo-studio", "LICENSE"));
  context.emitFile({
    type: "asset",
    fileName: "licenses/THIRD_PARTY_NOTICES.json",
    source: `${JSON.stringify(json, null, 2)}\n`,
  });
  context.emitFile({
    type: "asset",
    fileName: "licenses/THIRD_PARTY_NOTICES.txt",
    source: textInventory(packages),
  });
  context.emitFile({
    type: "asset",
    fileName: "licenses/THIRD_PARTY_LICENSES.txt",
    source: licenseText(licenses),
  });
  context.emitFile({
    type: "asset",
    fileName: "licenses/marimo/LICENSE",
    source: marimoLicense,
  });
  context.emitFile({
    type: "asset",
    fileName: "licenses/marimo-studio/LICENSE",
    source: studioLicense,
  });
};

export const browserLicenseInventory = () => {
  const moduleIds = new Set<string>();
  const collector = (): Plugin => ({
    name: "marimo-studio-browser-license-collector",
    apply: "build",
    generateBundle: {
      order: "post",
      handler(_options, bundle) {
        collectModuleIds(bundle, moduleIds);
      },
    },
  });
  const emitter = {
    name: "marimo-studio-browser-license-inventory",
    apply: "build",
    buildStart() {
      moduleIds.clear();
    },
    configResolved(config) {
      if (config.build.watch) {
        throw new Error("Browser license inventory requires a one-shot production build");
      }
    },
    generateBundle: {
      order: "post",
      async handler(_options, bundle) {
        collectModuleIds(bundle, moduleIds);
        await emitInventory(this, moduleIds);
      },
    },
  } satisfies Plugin;
  return { collector, emitter };
};
