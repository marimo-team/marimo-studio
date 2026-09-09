import { outputReadRequestSchema } from "@marimo-studio/protocol/output-read";
import { valueReadRequestSchema } from "@marimo-studio/protocol/value-read";

import type { BrowserRequestIdentity, BrowserRequestOwner } from "./request-identity.ts";

export type ProjectionReadKind = "outputs" | "values";
const PROJECTION_READ_ROUTE =
  /\/_marimo-studio\/presentation\/[^/]+\/_marimo-studio\/views\/[^/]+\/(outputs|values)$/;

export const projectionReadRouteKind = (url: string): ProjectionReadKind | undefined => {
  const match = PROJECTION_READ_ROUTE.exec(new URL(url).pathname);
  const kind = match?.[1];
  return kind === "outputs" || kind === "values" ? kind : undefined;
};

export const projectionReadRequestKind = (
  request: BrowserRequestIdentity,
): ProjectionReadKind | undefined =>
  request.method() === "POST" ? projectionReadRouteKind(request.url()) : undefined;
export type ProjectionReadSuccessorPolicy = "exact" | "view-transition";

interface ProjectionReadWireIdentity {
  readonly activeProjections: readonly string[] | undefined;
  readonly activeTargets: readonly string[] | undefined;
  readonly projections: readonly string[];
  readonly revision: string;
  readonly targets: readonly string[];
}

interface ProjectionReadOperation {
  readonly candidate: boolean;
  readonly kind: ProjectionReadKind;
  readonly start: number;
  readonly wire: ProjectionReadWireIdentity | undefined;
}

const projectionTuple = (projection: {
  readonly instanceId: string;
  readonly siteId: string;
  readonly target: string;
}): string => JSON.stringify([projection.siteId, projection.instanceId, projection.target]);

const projectionWireIdentity = (
  request: BrowserRequestIdentity,
  kind: ProjectionReadKind,
): ProjectionReadWireIdentity | undefined => {
  const body = request.postData();
  if (body === null) {
    return undefined;
  }
  try {
    const value = JSON.parse(body);
    const parsed =
      kind === "outputs"
        ? outputReadRequestSchema.safeParse(value)
        : valueReadRequestSchema.safeParse(value);
    if (!parsed.success) {
      return undefined;
    }
    const projections = parsed.data.projections.map(projectionTuple).sort();
    const targets = parsed.data.projections.map((projection) => projection.target).sort();
    if (kind === "values") {
      return {
        activeProjections: undefined,
        activeTargets: undefined,
        projections,
        revision: parsed.data.revision,
        targets,
      };
    }
    const output = outputReadRequestSchema.parse(value);
    return {
      activeProjections: output.activeProjections.map(projectionTuple).sort(),
      activeTargets: output.activeProjections.map((projection) => projection.target).sort(),
      projections,
      revision: output.revision,
      targets,
    };
  } catch {
    return undefined;
  }
};

const equalList = (left: readonly string[], right: readonly string[]): boolean =>
  left.length === right.length && left.every((value, index) => value === right[index]);

export class ProjectionReadRequestWindow {
  private readonly requests = new Map<BrowserRequestIdentity, ProjectionReadOperation>();
  private readonly pendingAborts: ProjectionReadOperation[] = [];
  private readonly successfulReads: ProjectionReadOperation[] = [];
  private readonly terminalValueTargets = new Set<string>();
  private accepting = true;
  private aborts = 0;
  private unsealedRecovery = false;
  private invalidValueTerminalization = false;
  private invalidRecovery = false;
  private overflowed = false;
  private postTerminalValueRead = false;
  private isRecovered = false;
  private isDisposed = false;

  constructor(
    private readonly owner: BrowserRequestOwner,
    private readonly initialProjectionRevision: string,
    private readonly limit = 512,
    private readonly successorPolicy: ProjectionReadSuccessorPolicy = "exact",
  ) {
    if (!Number.isSafeInteger(limit) || limit < 1) {
      throw new RangeError("Projection read capture requires a positive request limit.");
    }
  }

  recordStart(request: BrowserRequestIdentity, owner: BrowserRequestOwner, start: number): boolean {
    const kind = projectionReadRequestKind(request);
    if (owner !== this.owner || kind === undefined || this.isRecovered || this.isDisposed) {
      return false;
    }
    if (kind === "values" && this.terminalValueTargets.size > 0) {
      this.postTerminalValueRead = true;
      return false;
    }
    if (this.requests.has(request)) {
      return true;
    }
    if (this.requests.size + this.pendingAborts.length >= this.limit) {
      this.overflowed = true;
      return false;
    }
    this.requests.set(request, {
      candidate: this.accepting,
      kind,
      start,
      wire: projectionWireIdentity(request, kind),
    });
    return true;
  }

  recordAbort(request: BrowserRequestIdentity): boolean {
    const operation = this.requests.get(request);
    if (operation === undefined) {
      return false;
    }
    this.requests.delete(request);
    if (!operation.candidate) {
      return false;
    }
    if (operation.kind === "values" && operation.wire?.projections.length === 0) {
      this.pruneSuccessfulReads();
      return true;
    }
    this.aborts += 1;
    if (this.isTerminalValueOperation(operation)) {
      this.pruneSuccessfulReads();
      return true;
    }
    if (!this.successfulReads.some((successor) => this.replaces(operation, successor))) {
      this.pendingAborts.push(operation);
    }
    this.pruneSuccessfulReads();
    return true;
  }

  recordResponse(
    request: BrowserRequestIdentity,
    owner: BrowserRequestOwner,
    _start: number,
    status: number,
  ): void {
    const operation = this.requests.get(request);
    this.requests.delete(request);
    if (owner !== this.owner || operation === undefined || status !== 200) {
      return;
    }
    for (let index = this.pendingAborts.length - 1; index >= 0; index -= 1) {
      const abort = this.pendingAborts[index];
      if (abort !== undefined && this.replaces(abort, operation)) {
        this.pendingAborts.splice(index, 1);
      }
    }
    if (
      [...this.requests.values()].some(
        (candidate) => candidate.candidate && this.replaces(candidate, operation),
      )
    ) {
      this.successfulReads.push(operation);
      if (this.successfulReads.length > this.limit) {
        this.successfulReads.splice(0, this.successfulReads.length - this.limit);
      }
    }
  }

  recordFailure(request: BrowserRequestIdentity): void {
    this.requests.delete(request);
    this.pruneSuccessfulReads();
  }

  seal(): void {
    this.accepting = false;
  }

  terminalizeValues(targets: readonly string[]): boolean {
    if (
      !this.accepting ||
      this.isRecovered ||
      this.isDisposed ||
      targets.length === 0 ||
      targets.some((target) => target.length === 0)
    ) {
      this.invalidValueTerminalization = true;
      return false;
    }
    targets.forEach((target) => this.terminalValueTargets.add(target));
    for (let index = this.pendingAborts.length - 1; index >= 0; index -= 1) {
      const abort = this.pendingAborts[index];
      if (abort !== undefined && this.isTerminalValueOperation(abort)) {
        this.pendingAborts.splice(index, 1);
      }
    }
    return true;
  }

  recover(currentProjectionRevision: string): boolean {
    if (this.accepting) {
      this.unsealedRecovery = true;
      return false;
    }
    if (currentProjectionRevision === this.initialProjectionRevision) {
      this.invalidRecovery = true;
      return false;
    }
    if (!this.readyToRecover(currentProjectionRevision)) {
      return false;
    }
    this.accepting = false;
    this.isRecovered = true;
    return true;
  }

  readyToRecover(currentProjectionRevision: string): boolean {
    return (
      !this.accepting &&
      !this.isRecovered &&
      !this.isDisposed &&
      currentProjectionRevision !== this.initialProjectionRevision &&
      this.requests.size === 0 &&
      this.pendingAborts.length === 0 &&
      !this.overflowed &&
      !this.invalidRecovery &&
      !this.unsealedRecovery &&
      !this.invalidValueTerminalization &&
      !this.postTerminalValueRead
    );
  }

  dispose(): void {
    this.accepting = false;
    this.isDisposed = true;
  }

  diagnostics(): string[] {
    const messages: string[] = [];
    if (this.overflowed) {
      messages.push("projection read capture exceeded its request limit");
    }
    if (this.invalidRecovery) {
      messages.push("projection read capture recovered before its revision changed");
    }
    if (this.unsealedRecovery) {
      messages.push("projection read capture recovered before it was sealed");
    }
    if (this.invalidValueTerminalization) {
      messages.push("projection read capture terminalized values outside its mutation window");
    }
    if (this.postTerminalValueRead) {
      messages.push("projection read capture observed a values request after terminalization");
    }
    if (this.requests.size > 0) {
      messages.push(`projection read capture retained ${this.requests.size} active request(s)`);
    }
    if (this.aborts > 0 && !this.isRecovered) {
      messages.push("projection read capture observed aborts without a recovered revision");
    }
    if (this.pendingAborts.length > 0) {
      messages.push(
        `projection read capture retained ${this.pendingAborts.length} abort(s) without a newer successful read`,
      );
    }
    return messages;
  }

  private isTerminalValueOperation(operation: ProjectionReadOperation): boolean {
    return (
      operation.kind === "values" &&
      operation.wire !== undefined &&
      operation.wire.targets.length > 0 &&
      operation.wire.targets.every((target) => this.terminalValueTargets.has(target))
    );
  }

  private replaces(aborted: ProjectionReadOperation, successor: ProjectionReadOperation): boolean {
    if (
      successor.start <= aborted.start ||
      successor.kind !== aborted.kind ||
      aborted.wire === undefined ||
      successor.wire === undefined ||
      (successor.wire.revision === aborted.wire.revision &&
        (aborted.kind !== "values" || this.successorPolicy !== "exact"))
    ) {
      return false;
    }
    if (this.successorPolicy === "exact") {
      if (
        aborted.kind === "outputs" &&
        aborted.wire.projections.length === 0 &&
        aborted.wire.activeProjections !== undefined &&
        successor.wire.activeProjections !== undefined
      ) {
        return equalList(aborted.wire.activeProjections, successor.wire.activeProjections);
      }
      return equalList(aborted.wire.projections, successor.wire.projections);
    }
    if (equalList(aborted.wire.targets, successor.wire.targets)) {
      return true;
    }
    if (aborted.kind !== "outputs" || aborted.wire.targets.length === 0) {
      return false;
    }
    const activeTargets = new Set(successor.wire.activeTargets ?? []);
    return aborted.wire.targets.every((target) => !activeTargets.has(target));
  }

  private pruneSuccessfulReads(): void {
    for (let index = this.successfulReads.length - 1; index >= 0; index -= 1) {
      const successor = this.successfulReads[index];
      if (
        successor === undefined ||
        ![...this.requests.values()].some(
          (candidate) => candidate.candidate && this.replaces(candidate, successor),
        )
      ) {
        this.successfulReads.splice(index, 1);
      }
    }
  }
}
