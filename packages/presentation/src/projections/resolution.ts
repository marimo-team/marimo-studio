import type {
  MountDeclaration,
  ProjectionKind,
  ProjectionRequest,
  ProjectionTarget,
  SourceLocation,
} from "@marimo-studio/protocol/projections";
import type { RuntimeConfig } from "@marimo-studio/protocol/runtime-config";

import {
  PROJECTION_UNPAIRED_SURROGATE_CODE,
  projectionStringIsWellFormed,
} from "@marimo-studio/protocol/projections";
import { z } from "zod";

import { ownRecordValue } from "../records.ts";
import { isArtifactProjectionHost } from "./artifact-host.ts";
import { projectionKindForHost, projectionTargetForHost } from "./identity.ts";
import { notifyProjectionResolutionStale } from "./staleness.ts";

export interface SelectorPathStep {
  readonly kind: "attribute" | "item";
  readonly value: string | number;
}

export interface RuntimeProjectionRequest extends ProjectionRequest {
  readonly kind: ProjectionKind;
}

export interface ResolvedProjection {
  readonly request: RuntimeProjectionRequest;
  readonly site: MountDeclaration;
  readonly producer: string;
  readonly variable: string | null;
  readonly selectorPath: readonly SelectorPathStep[];
  readonly dependencyClosure: readonly string[];
  readonly runtimeCellId: string | undefined;
  readonly bindingsStale: boolean;
}

export interface ProjectionResolutionFailure {
  readonly code: string;
  readonly message: string;
  readonly siteId: string;
  readonly instanceId: string;
  readonly kind: ProjectionKind;
  readonly target: string;
  readonly source?: SourceLocation;
}

export type ProjectionResolution =
  | { readonly ok: true; readonly value: ResolvedProjection }
  | { readonly ok: false; readonly error: ProjectionResolutionFailure };

type ProjectionFailure = Extract<ProjectionResolution, { readonly ok: false }>;

interface ParsedSelector {
  readonly variable: string;
  readonly path: readonly SelectorPathStep[];
}

type ParsedSelectorResult =
  | { readonly ok: true; readonly value: ParsedSelector }
  | { readonly ok: false; readonly code?: string; readonly message: string };

type ProducerResolution =
  | { readonly ok: true; readonly value: Extract<ProjectionTarget, { status: "ready" }> }
  | ProjectionFailure;

const IDENTIFIER = /^[A-Za-z_][A-Za-z0-9_]*/;
const INDEX = /^(?:0|[1-9][0-9]*)/;
const HOST_SELECTOR = "marimo-cell, marimo-output, [mo-value]";

const failure = (
  request: RuntimeProjectionRequest,
  code: string,
  message: string,
  site?: MountDeclaration,
): ProjectionFailure => ({
  ok: false,
  error: {
    code,
    message,
    siteId: request.siteId,
    instanceId: request.instanceId,
    kind: request.kind,
    target: request.target,
    source: site?.source,
  },
});

const parseSelector = (target: string, maxPathSteps: number): ParsedSelectorResult => {
  const source = target.trim();
  const root = IDENTIFIER.exec(source);
  if (root === null) {
    return {
      ok: false,
      message: "A value target must start with a notebook variable name.",
    };
  }
  const path: SelectorPathStep[] = [];
  let position = root[0].length;
  while (position < source.length) {
    const suffix = source.slice(position);
    if (suffix.startsWith(".")) {
      const selected = IDENTIFIER.exec(suffix.slice(1));
      if (selected === null) {
        return { ok: false, message: "Dot selection requires an object key." };
      }
      if (selected[0].startsWith("_")) {
        return { ok: false, message: "Private attribute selection is unavailable." };
      }
      path.push({ kind: "attribute", value: selected[0] });
      position += selected[0].length + 1;
    } else if (suffix.startsWith("[")) {
      const content = suffix.slice(1);
      const selectedIndex = INDEX.exec(content);
      if (selectedIndex !== null) {
        const index = Number(selectedIndex[0]);
        if (!Number.isSafeInteger(index)) {
          return {
            ok: false,
            message: "Bracket indexes must be JavaScript safe integers.",
          };
        }
        path.push({ kind: "item", value: index });
        position += selectedIndex[0].length + 1;
      } else if (content.startsWith('"')) {
        let selected: unknown;
        let consumed = 0;
        for (let end = 2; end <= content.length; end += 1) {
          try {
            selected = JSON.parse(content.slice(0, end));
            consumed = end;
            break;
          } catch {
            // Continue until one complete JSON string has been consumed.
          }
        }
        const selectedKey = z.string().safeParse(selected);
        if (!selectedKey.success) {
          return {
            ok: false,
            message: "Bracket object keys must be JSON strings.",
          };
        }
        if (!projectionStringIsWellFormed(selectedKey.data)) {
          return {
            ok: false,
            code: PROJECTION_UNPAIRED_SURROGATE_CODE,
            message: "Projection targets and instance IDs require well-formed Unicode.",
          };
        }
        path.push({ kind: "item", value: selectedKey.data });
        position += consumed + 1;
      } else {
        return {
          ok: false,
          message: "Brackets require a non-negative integer or JSON string.",
        };
      }
      if (source[position] !== "]") {
        return {
          ok: false,
          message: "Bracket selection requires a closing ].",
        };
      }
      position += 1;
    } else {
      return {
        ok: false,
        message: "A value target may contain dot selection and bracket indexing.",
      };
    }
    if (path.length > maxPathSteps) {
      return {
        ok: false,
        message: `A value target may contain at most ${maxPathSteps} path steps.`,
      };
    }
  }
  return { ok: true, value: { variable: root[0], path } };
};

const oneProducer = (
  request: RuntimeProjectionRequest,
  target: ProjectionTarget | undefined,
  noun: string,
  site: MountDeclaration,
): ProducerResolution => {
  const codeNoun = noun === "cell" ? "" : `-${noun}`;
  if (target === undefined) {
    return failure(
      request,
      `projection-${request.kind}${codeNoun}-not-found`,
      `${noun === "cell" ? "Cell target" : "Notebook variable"} ${JSON.stringify(
        request.target,
      )} does not resolve in this notebook.`,
      site,
    );
  }
  if (target.status === "ambiguous") {
    return failure(
      request,
      `projection-${request.kind}${codeNoun}-ambiguous`,
      `${noun === "cell" ? "Cell target" : "Notebook variable"} ${JSON.stringify(
        request.target,
      )} has multiple notebook producers.`,
      site,
    );
  }
  return { ok: true, value: target };
};

export const resolveProjection = (
  config: RuntimeConfig,
  request: RuntimeProjectionRequest,
  context?: ProjectionResolutionContext,
): ProjectionResolution => {
  if (
    !projectionStringIsWellFormed(request.instanceId) ||
    !projectionStringIsWellFormed(request.target)
  ) {
    return failure(
      request,
      PROJECTION_UNPAIRED_SURROGATE_CODE,
      "Projection targets and instance IDs require well-formed Unicode.",
    );
  }
  if (
    new TextEncoder().encode(request.instanceId).length > config.projectionPolicy.maxInstanceIdBytes
  ) {
    return failure(
      request,
      "projection-instance-id-too-large",
      "The projection instance identifier exceeds the runtime limit.",
    );
  }
  if (new TextEncoder().encode(request.target).length > config.projectionPolicy.maxTargetBytes) {
    return failure(
      request,
      "projection-target-too-large",
      "The projection target exceeds the runtime limit.",
    );
  }
  const matches =
    context?.site(request.siteId) ?? config.mounts.filter((site) => site.id === request.siteId);
  if (matches.length !== 1) {
    return failure(
      request,
      "projection-site-not-found",
      request.siteId
        ? `Projection site ${JSON.stringify(request.siteId)} is unavailable.`
        : "The mounted projection has no provider source-site identity.",
    );
  }
  const site = matches[0];
  if (site.kind !== request.kind) {
    return failure(
      request,
      "projection-kind-mismatch",
      `Projection site ${JSON.stringify(site.id)} cannot request ${request.kind} targets.`,
      site,
    );
  }
  if (request.target.length === 0) {
    return failure(
      request,
      "projection-target-empty",
      "A mounted projection target must not be empty.",
      site,
    );
  }
  if (site.allowedTargets !== null && !site.allowedTargets.includes(request.target)) {
    return failure(
      request,
      "projection-target-not-allowed",
      `Projection target ${JSON.stringify(request.target)} is not allowed by this mount.`,
      site,
    );
  }

  let producer: ProducerResolution;
  let variable: string | null = null;
  let selectorPath: readonly SelectorPathStep[] = [];
  if (request.kind === "cell") {
    producer = oneProducer(
      request,
      ownRecordValue(config.projectionTargets.cells, request.target),
      "cell",
      site,
    );
  } else {
    const parsed = parseSelector(request.target, config.projectionPolicy.maxPathSteps);
    if (!parsed.ok) {
      return failure(request, parsed.code ?? "projection-target-invalid", parsed.message, site);
    }
    variable = parsed.value.variable;
    selectorPath = parsed.value.path;
    producer = oneProducer(
      request,
      ownRecordValue(config.projectionTargets.variables, parsed.value.variable),
      "variable",
      site,
    );
  }
  if (!producer.ok) {
    return producer;
  }
  const producerRef = producer.value.producer;
  const dependencyClosure = producer.value.dependencyClosure;
  const runtimeBindings = config.runtimeBindings.cellRefs;
  const bindingsStale =
    Object.keys(runtimeBindings).length > 0 &&
    dependencyClosure.some((reference) => ownRecordValue(runtimeBindings, reference) === undefined);
  return {
    ok: true,
    value: {
      request,
      site,
      producer: producerRef,
      variable,
      selectorPath,
      dependencyClosure,
      runtimeCellId: ownRecordValue(runtimeBindings, producerRef),
      bindingsStale,
    },
  };
};

export interface ProjectionResolutionContext {
  activeIndex(host: Element): number | undefined;
  hosts(): readonly Element[];
  site(id: string): readonly MountDeclaration[];
  targetRank(kind: ProjectionKind, target: string): number | undefined;
}

export const createProjectionResolutionContext = (
  config: RuntimeConfig,
  root: ParentNode,
): ProjectionResolutionContext => {
  const sites = new Map<string, MountDeclaration[]>();
  config.mounts.forEach((site) => {
    const matches = sites.get(site.id) ?? [];
    matches.push(site);
    sites.set(site.id, matches);
  });
  const hosts = Array.from(root.querySelectorAll(HOST_SELECTOR)).filter(isArtifactProjectionHost);
  const activeIndexes = new Map(hosts.map((host, index) => [host, index]));
  const ranks: Record<ProjectionKind, Map<string, number>> = {
    cell: new Map(),
    output: new Map(),
    value: new Map(),
  };
  hosts.forEach((host, index) => {
    const kind = projectionKindForHost(host);
    const target = projectionTargetForHost(host, kind);
    const resolved = resolveProjection(config, {
      siteId: host.getAttribute("data-marimo-studio-site")?.trim() ?? "",
      instanceId: `quota-${index}`,
      kind,
      target,
    });
    if (!resolved.ok) {
      return;
    }
    const selected = ranks[kind];
    if (!selected.has(target)) {
      selected.set(target, selected.size);
    }
  });
  return {
    activeIndex: (host) => activeIndexes.get(host),
    hosts: () => hosts,
    site: (id) => sites.get(id) ?? [],
    targetRank: (kind, target) => ranks[kind].get(target),
  };
};

export const resolveHostProjection = (
  config: RuntimeConfig,
  host: Element,
  request: RuntimeProjectionRequest,
  context: ProjectionResolutionContext = createProjectionResolutionContext(
    config,
    host.ownerDocument,
  ),
): ProjectionResolution => {
  const resolved = resolveProjection(config, request, context);
  if (!resolved.ok) {
    return resolved;
  }
  if (resolved.value.bindingsStale) {
    notifyProjectionResolutionStale(config.projectionRevision);
  }
  const activeIndex = context.activeIndex(host);
  if (activeIndex === undefined || activeIndex >= config.projectionPolicy.maxActiveInstances) {
    return failure(
      request,
      "projection-instance-limit",
      `A presentation may mount at most ${config.projectionPolicy.maxActiveInstances} projection instances.`,
      resolved.value.site,
    );
  }
  const limits: Record<ProjectionKind, number> = {
    cell: config.projectionPolicy.maxUniqueCellTargets,
    output: config.projectionPolicy.maxUniqueOutputTargets,
    value: config.projectionPolicy.maxUniqueValueTargets,
  };
  const limit = ownRecordValue(limits, request.kind);
  if (limit === undefined) {
    return failure(
      request,
      "projection-kind-mismatch",
      "The mounted projection kind is unavailable.",
      resolved.value.site,
    );
  }
  const targetRank = context.targetRank(request.kind, request.target);
  if (targetRank !== undefined && targetRank >= limit) {
    return failure(
      request,
      `projection-${request.kind}-target-limit`,
      `A presentation may mount at most ${limit} unique ${request.kind} targets.`,
      resolved.value.site,
    );
  }
  return resolved;
};
