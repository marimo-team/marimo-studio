import { WORKSPACE_STREAM_QUERY_PARAM } from "@marimo-studio/protocol/query";

export interface BrowserRequestIdentity {
  method(): string;
  postData(): string | null;
  resourceType(): string;
  url(): string;
}

export interface BrowserRequestOwner {
  readonly id: number;
}

export interface OwnedRequestAbort<Request extends object, Owner extends object> {
  readonly owner: Owner;
  readonly request: Request;
  readonly start: number | undefined;
}

export const requestAbortsRetiredByDocument = <Operation extends OwnedRequestAbort<object, object>>(
  pending: Iterable<Operation>,
  owner: Operation["owner"],
  documentStart: number,
): Operation[] =>
  [...pending].filter(
    (operation) =>
      operation.owner === owner && operation.start !== undefined && operation.start < documentStart,
  );

export class BrowserRequestOwners<Source extends object> {
  private readonly owners = new WeakMap<Source, BrowserRequestOwner>();
  private nextOwnerId = 0;

  constructor(
    private readonly createOwner: () => BrowserRequestOwner = () => ({
      id: ++this.nextOwnerId,
    }),
  ) {}

  ownerFor(source: Source): BrowserRequestOwner {
    let owner = this.owners.get(source);
    if (owner === undefined) {
      owner = this.createOwner();
      this.owners.set(source, owner);
    }
    return owner;
  }
}

export const browserRequestIdentity = (request: BrowserRequestIdentity): string =>
  [request.method(), request.url(), request.resourceType(), request.postData() ?? ""].join(
    "\u0000",
  );

export class ExactRequestAbortWitness<Request extends object> {
  private completionFailed = false;
  private completed = false;
  private invalidRecovery = false;
  private isRecovered = false;
  private seen = 0;
  private readonly observed: Promise<void>;
  private resolveObserved!: () => void;

  constructor(
    private readonly request: Request,
    completion: Promise<void>,
  ) {
    this.observed = new Promise((resolve) => {
      this.resolveObserved = resolve;
    });
    void completion.then(
      () => {
        this.completed = true;
      },
      () => {
        this.completionFailed = true;
      },
    );
  }

  recordFailure(request: Request, errorText: string): boolean {
    if (request !== this.request || errorText !== "net::ERR_ABORTED" || this.seen > 0) {
      return false;
    }
    this.seen = 1;
    this.resolveObserved();
    return true;
  }

  waitForAbort(): Promise<void> {
    return this.observed;
  }

  recover(): boolean {
    if (!this.completed || this.seen !== 1) {
      this.invalidRecovery = true;
      return false;
    }
    this.isRecovered = true;
    return true;
  }

  diagnostics(): string[] {
    const messages: string[] = [];
    if (this.completionFailed) {
      messages.push("exact held request completion rejected");
    }
    if (this.invalidRecovery) {
      messages.push("exact held request abort recovered before request completion");
    }
    if (this.seen === 0) {
      messages.push("expected exact held request abort, saw none");
    } else if (!this.isRecovered) {
      messages.push("exact held request abort had no observed recovery");
    }
    return messages;
  }
}

interface RequestOperation {
  generation: number;
  identity: string;
  start: number;
}

interface RecoveryGeneration {
  generation: number;
  inFlight: Set<BrowserRequestIdentity>;
  pendingAborts: number[];
  retainPendingAborts: boolean;
  successCredits: number[];
}

interface ReadRecoveryIdentity {
  identity: string;
  retainPendingAborts: boolean;
}

const IDEMPOTENT_READ_METHODS = new Set(["GET", "HEAD"]);

export const isIdempotentReadRequest = (request: BrowserRequestIdentity): boolean =>
  IDEMPOTENT_READ_METHODS.has(request.method());

const idempotentReadRecoveryIdentity = (request: BrowserRequestIdentity): ReadRecoveryIdentity => {
  if (request.method() !== "GET" || request.resourceType() !== "document") {
    return {
      identity: browserRequestIdentity(request),
      retainPendingAborts: false,
    };
  }
  const url = new URL(request.url());
  const presentation = /^(.*\/_marimo-studio\/presentation\/)[^/]+(\/[^/]+\/$)/.exec(url.pathname);
  if (presentation === null && !url.searchParams.has("marimo_studio_renewal")) {
    return {
      identity: browserRequestIdentity(request),
      retainPendingAborts: false,
    };
  }
  const presentationPrefix = "/_marimo-studio/presentation/";
  const routePath =
    presentation === null
      ? url.pathname
      : `${presentation[1]!.slice(0, -presentationPrefix.length)}${presentation[2]!}`;
  return {
    identity: [
      request.method(),
      url.origin,
      routePath,
      request.resourceType(),
      url.searchParams.get("file") ?? "",
      url.searchParams.get("runtime") ?? "",
      request.postData() ?? "",
    ].join("\u0000"),
    retainPendingAborts: true,
  };
};

export const abortedResponseCompleted = (
  request: BrowserRequestIdentity,
  status: number | undefined,
  requestFinished = false,
): boolean =>
  isIdempotentReadRequest(request) &&
  status !== undefined &&
  (request.method() === "HEAD"
    ? status < 400
    : [204, 205, 304].includes(status) ||
      (requestFinished &&
        ((request.resourceType() === "document" && status >= 200 && status < 300) ||
          (request.resourceType() === "fetch" &&
            status === 202 &&
            /\/_marimo-studio\/presentation\/[^/]+\/[^/]+\/$/.test(
              new URL(request.url()).pathname,
            )))));

export class IdempotentReadRecovery {
  private readonly operations = new WeakMap<BrowserRequestIdentity, RequestOperation>();
  private readonly completed = new WeakSet<BrowserRequestIdentity>();
  private readonly generations = new Map<string, RecoveryGeneration>();
  private nextGeneration = 0;
  private nextStart = 0;

  constructor(private readonly limit = 512) {}

  recordStart(request: BrowserRequestIdentity, owner: BrowserRequestOwner): number | undefined {
    if (!isIdempotentReadRequest(request)) {
      return undefined;
    }
    const current = this.operations.get(request);
    if (current !== undefined) {
      return current.start;
    }
    const recovery = idempotentReadRecoveryIdentity(request);
    const identity = `${owner.id}\u0000${recovery.identity}`;
    let generation = this.generations.get(identity);
    if (generation === undefined) {
      generation = {
        generation: ++this.nextGeneration,
        inFlight: new Set(),
        pendingAborts: [],
        retainPendingAborts: recovery.retainPendingAborts,
        successCredits: [],
      };
      this.generations.set(identity, generation);
    }
    const start = ++this.nextStart;
    generation.inFlight.add(request);
    this.operations.set(request, { generation: generation.generation, identity, start });
    return start;
  }

  startOrdinal(request: BrowserRequestIdentity): number | undefined {
    return this.operations.get(request)?.start;
  }

  recordSuccess(request: BrowserRequestIdentity): number | undefined {
    const terminal = this.beginTerminal(request);
    if (!terminal) {
      return undefined;
    }
    const { generation, operation } = terminal;
    const recovered = this.takeGreatestBelow(generation.pendingAborts, operation.start);
    if (recovered === undefined) {
      this.retain(generation.successCredits, operation.start);
    }
    this.closeIfIdle(operation.identity, generation);
    return recovered;
  }

  recordAbort(request: BrowserRequestIdentity): boolean {
    const terminal = this.beginTerminal(request);
    if (!terminal) {
      return false;
    }
    const { generation, operation } = terminal;
    const recovered =
      this.takeSmallestAbove(generation.successCredits, operation.start) !== undefined;
    if (!recovered) {
      this.retain(generation.pendingAborts, operation.start);
    }
    this.closeIfIdle(operation.identity, generation);
    return recovered;
  }

  recordFailure(request: BrowserRequestIdentity): void {
    const terminal = this.beginTerminal(request);
    if (terminal) {
      this.closeIfIdle(terminal.operation.identity, terminal.generation);
    }
  }

  discardAbort(request: BrowserRequestIdentity): void {
    const operation = this.operations.get(request);
    if (!operation) {
      return;
    }
    const generation = this.generations.get(operation.identity);
    if (generation?.generation !== operation.generation) {
      return;
    }
    const abort = generation.pendingAborts.indexOf(operation.start);
    if (abort >= 0) {
      generation.pendingAborts.splice(abort, 1);
    }
    this.closeIfIdle(operation.identity, generation);
  }

  dispose(): void {
    this.generations.clear();
  }

  private beginTerminal(
    request: BrowserRequestIdentity,
  ): { generation: RecoveryGeneration; operation: RequestOperation } | undefined {
    if (this.completed.has(request)) {
      return undefined;
    }
    const operation = this.operations.get(request);
    if (!operation) {
      return undefined;
    }
    this.completed.add(request);
    const generation = this.generations.get(operation.identity);
    if (generation?.generation !== operation.generation) {
      return undefined;
    }
    generation.inFlight.delete(request);
    return { generation, operation };
  }

  private closeIfIdle(identity: string, generation: RecoveryGeneration): void {
    if (
      generation.inFlight.size === 0 &&
      (!generation.retainPendingAborts || generation.pendingAborts.length === 0) &&
      this.generations.get(identity) === generation
    ) {
      this.generations.delete(identity);
    }
  }

  private retain(values: number[], start: number): void {
    values.push(start);
    if (values.length > this.limit) {
      values.splice(0, values.length - this.limit);
    }
  }

  private takeGreatestBelow(values: number[], bound: number): number | undefined {
    let best = -1;
    for (let index = 0; index < values.length; index += 1) {
      const candidate = values[index];
      const previous = best < 0 ? undefined : values[best];
      if (
        candidate !== undefined &&
        candidate < bound &&
        (previous === undefined || candidate > previous)
      ) {
        best = index;
      }
    }
    return this.takeAt(values, best);
  }

  private takeSmallestAbove(values: number[], bound: number): number | undefined {
    let best = -1;
    for (let index = 0; index < values.length; index += 1) {
      const candidate = values[index];
      const previous = best < 0 ? undefined : values[best];
      if (
        candidate !== undefined &&
        candidate > bound &&
        (previous === undefined || candidate < previous)
      ) {
        best = index;
      }
    }
    return this.takeAt(values, best);
  }

  private takeAt(values: number[], index: number): number | undefined {
    if (index < 0) {
      return undefined;
    }
    const [value] = values.splice(index, 1);
    return value;
  }
}

interface WorkspaceEventStreamOperation {
  readonly generation: number;
  readonly owner: BrowserRequestOwner;
  ready: boolean;
}

interface WorkspaceEventStreamAbort {
  readonly generation: number;
  readonly owner: BrowserRequestOwner;
}

export class WorkspaceEventStreamReplacementWindow {
  private readonly requests = new Map<BrowserRequestIdentity, WorkspaceEventStreamOperation>();
  private readonly pendingAborts: WorkspaceEventStreamAbort[] = [];
  private readonly replacedOwners = new Set<BrowserRequestOwner>();
  private readonly origin: string;
  private readonly pathname: string;
  private accepting = true;
  private invalidGeneration = false;
  private invalidOwnerRetirement = false;
  private invalidRecovery = false;
  private isRecovered = false;
  private replacements = 0;

  constructor(
    eventsUrl: string,
    private readonly expectedReplacements = 1,
  ) {
    const route = new URL(eventsUrl);
    if (route.search || route.hash) {
      throw new Error("Workspace event stream routes must not include a query or fragment.");
    }
    if (!Number.isSafeInteger(expectedReplacements) || expectedReplacements < 1) {
      throw new RangeError("Workspace event stream replacements require a positive count.");
    }
    this.origin = route.origin;
    this.pathname = route.pathname;
  }

  recordStart(request: BrowserRequestIdentity, owner: BrowserRequestOwner): boolean {
    if (!this.accepting || this.isRecovered || !this.matches(request)) {
      return false;
    }
    if (this.requests.has(request)) {
      return true;
    }
    const url = new URL(request.url());
    const generations = url.searchParams.getAll(WORKSPACE_STREAM_QUERY_PARAM);
    const generation = generations.length === 1 ? Number(generations[0]) : Number.NaN;
    if (!Number.isSafeInteger(generation) || generation <= 0) {
      this.invalidGeneration = true;
      return true;
    }
    this.requests.set(request, { generation, owner, ready: false });
    return true;
  }

  recordResponse(request: BrowserRequestIdentity, status: number): boolean {
    const operation = this.requests.get(request);
    if (operation === undefined) {
      return false;
    }
    if (status !== 200) {
      return true;
    }
    operation.ready = true;
    this.resolveAborts(operation);
    return true;
  }

  recordAbort(request: BrowserRequestIdentity): boolean {
    const operation = this.requests.get(request);
    if (operation === undefined || this.isRecovered) {
      return false;
    }
    this.requests.delete(request);
    const successor = this.readySuccessor(operation);
    if (successor === undefined) {
      this.pendingAborts.push(operation);
    } else {
      this.replacements += 1;
      this.replacedOwners.add(operation.owner);
    }
    return true;
  }

  recordFailure(request: BrowserRequestIdentity): boolean {
    return this.requests.delete(request);
  }

  retireOwner(owner: BrowserRequestOwner): boolean {
    const owned = [...this.requests.entries()].filter(([, operation]) => operation.owner === owner);
    const valid =
      !this.pendingAborts.some((operation) => operation.owner === owner) &&
      (!this.replacedOwners.has(owner) || (owned.length === 1 && owned[0]?.[1].ready === true));
    if (!valid) {
      this.invalidOwnerRetirement = true;
      return false;
    }
    owned.forEach(([request]) => this.requests.delete(request));
    this.replacedOwners.delete(owner);
    return true;
  }

  recover(): boolean {
    this.accepting = false;
    if (!this.readyToRecover()) {
      this.invalidRecovery = true;
      return false;
    }
    this.isRecovered = true;
    return true;
  }

  readyToRecover(): boolean {
    return !(
      this.invalidGeneration ||
      this.invalidOwnerRetirement ||
      this.pendingAborts.length > 0 ||
      this.replacements !== this.expectedReplacements ||
      !this.hasExactSurvivors()
    );
  }

  diagnostics(): string[] {
    const messages: string[] = [];
    if (this.invalidGeneration) {
      messages.push("workspace event stream replacement observed an invalid generation");
    }
    if (this.invalidOwnerRetirement) {
      messages.push("workspace event stream replacement retired an owner without one ready stream");
    }
    if (this.pendingAborts.length > 0) {
      messages.push(
        `workspace event stream replacement retained ${this.pendingAborts.length} abort(s) without a newer ready generation`,
      );
    }
    if (this.replacements !== this.expectedReplacements) {
      messages.push(
        `expected ${this.expectedReplacements} workspace event stream replacement(s), saw ${this.replacements}`,
      );
    }
    if (!this.hasExactSurvivors()) {
      messages.push(
        "workspace event stream replacement did not retain exactly one ready survivor per owner",
      );
    }
    if (this.invalidRecovery && this.pendingAborts.length > 0) {
      messages.push("workspace event stream replacement recovered before every abort was replaced");
    } else if (
      this.replacements === this.expectedReplacements &&
      !this.isRecovered &&
      !this.invalidRecovery
    ) {
      messages.push("workspace event stream replacement had no observed recovery");
    }
    return messages;
  }

  private matches(request: BrowserRequestIdentity): boolean {
    const url = new URL(request.url());
    return (
      request.method() === "GET" &&
      request.resourceType() === "eventsource" &&
      url.origin === this.origin &&
      url.pathname === this.pathname
    );
  }

  private readySuccessor(
    aborted: WorkspaceEventStreamAbort,
  ): WorkspaceEventStreamOperation | undefined {
    return [...this.requests.values()].find(
      (candidate) =>
        candidate.owner === aborted.owner &&
        candidate.generation > aborted.generation &&
        candidate.ready,
    );
  }

  private resolveAborts(successor: WorkspaceEventStreamOperation): void {
    for (let index = this.pendingAborts.length - 1; index >= 0; index -= 1) {
      const aborted = this.pendingAborts[index];
      if (
        aborted !== undefined &&
        aborted.owner === successor.owner &&
        aborted.generation < successor.generation
      ) {
        this.pendingAborts.splice(index, 1);
        this.replacements += 1;
        this.replacedOwners.add(successor.owner);
      }
    }
  }

  private hasExactSurvivors(): boolean {
    return [...this.replacedOwners].every((owner) => {
      const survivors = [...this.requests.values()].filter((request) => request.owner === owner);
      return survivors.length === 1 && survivors[0]?.ready === true;
    });
  }
}
