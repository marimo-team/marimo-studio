import {
  type PreparedPresentationHandle,
  requiresPreparedModelRemount,
  reconcileProjectedOutput,
  type releaseProjectedOutputResources,
  toMarimoCellOutput,
} from "@marimo-studio/marimo-frontend/prepared-presentation";
import { createElement } from "react";

import type { PreparedCellOutput, PreparedProjectionSnapshot } from "./records.ts";
import type { PreparedOutputOwners, PreparedResources } from "./resources.ts";

import { getRuntimeConfig } from "../runtime-config/index.ts";
import { applyValues } from "../values/hosts.ts";
import { PreparedProjectionCapabilityError } from "./errors.ts";
import { PreparedProjectionPortals } from "./portals.tsx";
import { modelResources, preparedOutputOwners, preparedValueRecord } from "./resources.ts";

type ReleaseProjectedOutputResources = typeof releaseProjectedOutputResources;
type PreparedUiValueStage = ReturnType<PreparedPresentationHandle["uiValues"]["stage"]>;
type PreparedModelReplacement = Awaited<
  ReturnType<PreparedPresentationHandle["models"]["replace"]>
>;

export const preparedFailure = (cause: unknown): Error =>
  cause instanceof Error || cause instanceof DOMException ? cause : new Error(String(cause));

export const attempt = (errors: Error[], action: () => void): void => {
  try {
    action();
  } catch (error) {
    errors.push(preparedFailure(error));
  }
};

export const attemptAsync = async (
  errors: Error[],
  action: () => void | Promise<void>,
): Promise<void> => {
  try {
    await action();
  } catch (error) {
    errors.push(preparedFailure(error));
  }
};

export const failureWithCleanup = (
  failure: Error,
  cleanupErrors: readonly Error[],
  message: string,
): Error =>
  cleanupErrors.length === 0 ? failure : new AggregateError([failure, ...cleanupErrors], message);

export const throwCleanupErrors = (errors: readonly Error[], message: string): void => {
  if (errors.length === 1) {
    throw errors[0];
  }
  if (errors.length > 1) {
    throw new AggregateError(errors, message);
  }
};

const outputUpdate = (
  ownerCellId: string,
  output: PreparedCellOutput,
  timestamp: number,
  resetUiObjectIds: readonly string[],
) => ({
  ownerCellId,
  channel: output.channel,
  mimetype: output.mimetype,
  data: output.data,
  timestamp,
  resetUiObjectIds,
});

export const releasePreparedOwners = (
  owners: PreparedOutputOwners,
  release: ReleaseProjectedOutputResources,
): void => {
  const errors: Error[] = [];
  owners.forEach((ids, owner) => attempt(errors, () => release(owner, ids)));
  throwCleanupErrors(errors, "Prepared projection owner release failed");
};

const releaseIntroducedOwners = (
  nextOwners: PreparedOutputOwners,
  previousOwners: PreparedOutputOwners,
  release: ReleaseProjectedOutputResources,
): void => {
  const errors: Error[] = [];
  nextOwners.forEach((ids, owner) => {
    const previousIds = previousOwners.get(owner) ?? [];
    const introducedIds = ids.filter((id) => !previousIds.includes(id));
    if (!previousOwners.has(owner) || introducedIds.length > 0) {
      attempt(errors, () => release(owner, introducedIds));
    }
  });
  throwCleanupErrors(errors, "Prepared projection staged-owner release failed");
};

const reconcileSnapshot = (
  snapshot: PreparedProjectionSnapshot,
  timestamp: number,
  previousOwners: PreparedOutputOwners,
  release: ReleaseProjectedOutputResources,
): Map<string, readonly string[]> => {
  const nextOwners = preparedOutputOwners(snapshot);
  const reconciledOwners = new Set<string>();
  const resetIds = (owner: string): readonly string[] => {
    if (reconciledOwners.has(owner)) {
      return [];
    }
    reconciledOwners.add(owner);
    const nextIds = nextOwners.get(owner) ?? [];
    return (previousOwners.get(owner) ?? []).filter((id) => !nextIds.includes(id));
  };
  for (const projected of snapshot.outputs) {
    if (projected.output === null) {
      continue;
    }
    toMarimoCellOutput(projected.output);
    reconcileProjectedOutput(
      outputUpdate(
        projected.ownerCellId,
        projected.output,
        timestamp,
        resetIds(projected.ownerCellId),
      ),
    );
  }
  for (const cell of snapshot.cells) {
    for (const output of cell.console) {
      if (output.channel === "stdin" || output.channel === "pdb") {
        throw new PreparedProjectionCapabilityError(
          "prepared-stdin-unsupported",
          `Prepared cell ${JSON.stringify(cell.alias)} requires ${output.channel} interaction.`,
        );
      }
      toMarimoCellOutput(output);
    }
    if (cell.output !== null) {
      toMarimoCellOutput(cell.output);
      reconcileProjectedOutput(
        outputUpdate(cell.cell.id, cell.output, timestamp, resetIds(cell.cell.id)),
      );
    }
  }
  previousOwners.forEach((ids, owner) => {
    if (!reconciledOwners.has(owner)) {
      const nextIds = nextOwners.get(owner) ?? [];
      release(
        owner,
        ids.filter((id) => !nextIds.includes(id)),
      );
    }
  });
  return nextOwners;
};

interface PreparedCommit {
  readonly owners: Map<string, readonly string[]>;
  readonly uiStage: PreparedUiValueStage;
  rollback(): void;
}

const commitSnapshot = (
  shell: PreparedPresentationHandle,
  snapshot: PreparedProjectionSnapshot,
  previousOwners: PreparedOutputOwners,
  resources: PreparedResources,
  portalRevision: number,
  release: ReleaseProjectedOutputResources,
): PreparedCommit => {
  const timestamp = Date.now();
  const snapshotOwners = preparedOutputOwners(snapshot);
  let uiStage: PreparedUiValueStage | undefined;
  const rollback = (): void => {
    const cleanupErrors: Error[] = [];
    attempt(cleanupErrors, () => uiStage?.rollback());
    attempt(cleanupErrors, () => releaseIntroducedOwners(snapshotOwners, previousOwners, release));
    throwCleanupErrors(cleanupErrors, "Prepared projection rollback failed");
  };
  try {
    uiStage = shell.uiValues.stage(resources.uiValues);
    const nextOwners = reconcileSnapshot(snapshot, timestamp, previousOwners, release);
    shell.render(
      createElement(PreparedProjectionPortals, {
        key: portalRevision,
        snapshot,
        timestamp,
      }),
    );
    applyValues(preparedValueRecord(snapshot), getRuntimeConfig().projectionRevision);
    return { owners: nextOwners, uiStage, rollback };
  } catch (error) {
    const cleanupErrors: Error[] = [];
    attempt(cleanupErrors, rollback);
    throw failureWithCleanup(
      preparedFailure(error),
      cleanupErrors,
      "Prepared projection commit and rollback failed",
    );
  }
};

const requiresPortalRemount = (
  failure: Error,
  models: PreparedModelReplacement | undefined,
): boolean => models?.remount === true || requiresPreparedModelRemount(failure);

export type PreparedSnapshotApplication =
  | {
      readonly ok: true;
      readonly owners: Map<string, readonly string[]>;
      readonly portalRevision: number;
    }
  | {
      readonly ok: false;
      readonly error: Error;
      readonly portalRevision: number;
    };

export const applyPreparedSnapshot = async ({
  shell,
  snapshot,
  previousOwners,
  resources,
  portalRevision,
  release,
  replaceModels,
  signal,
}: {
  readonly shell: PreparedPresentationHandle;
  readonly snapshot: PreparedProjectionSnapshot;
  readonly previousOwners: PreparedOutputOwners;
  readonly resources: PreparedResources;
  readonly portalRevision: number;
  readonly release: ReleaseProjectedOutputResources;
  readonly replaceModels: boolean;
  readonly signal?: AbortSignal;
}): Promise<PreparedSnapshotApplication> => {
  let committed: PreparedCommit | undefined;
  let models: PreparedModelReplacement | undefined;
  let nextPortalRevision = portalRevision;
  try {
    if (replaceModels) {
      models = await shell.models.replace(modelResources(resources), signal);
      nextPortalRevision = models.remount ? portalRevision + 1 : portalRevision;
    }
    signal?.throwIfAborted();
    committed = commitSnapshot(
      shell,
      snapshot,
      previousOwners,
      resources,
      nextPortalRevision,
      release,
    );
    signal?.throwIfAborted();
    await models?.commit();
    committed.uiStage.commit();
    return { ok: true, owners: committed.owners, portalRevision: nextPortalRevision };
  } catch (error) {
    const failure = preparedFailure(error);
    const cleanupErrors: Error[] = [];
    attempt(cleanupErrors, () => committed?.rollback());
    await attemptAsync(cleanupErrors, () => models?.rollback());
    if (requiresPortalRemount(failure, models)) {
      nextPortalRevision += 1;
    }
    return {
      ok: false,
      error: failureWithCleanup(
        failure,
        cleanupErrors,
        "Prepared projection application and rollback failed",
      ),
      portalRevision: nextPortalRevision,
    };
  }
};
