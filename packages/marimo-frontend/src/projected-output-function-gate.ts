export const PROJECTED_OUTPUT_SCOPE_ATTRIBUTE = "data-marimo-studio-projected-output";
export const PROJECTED_OUTPUT_ACTIVE_OWNER_ATTRIBUTE = "data-marimo-studio-active-projection-owner";
export const PROJECTED_OUTPUT_OWNER_ATTRIBUTE = "data-marimo-studio-output-projection-owner";
export const PROJECTED_OUTPUT_FUNCTION_ABORT_MESSAGE =
  "The projected output changed before its function request.";
export const PROJECTED_OUTPUT_FUNCTION_DRAIN_TIMEOUT_MS = 10_000;

export class ProjectedOutputFunctionDrainTimeoutError extends Error {
  constructor() {
    super("A projected output function request did not finish before the presentation refresh.");
    this.name = "ProjectedOutputFunctionDrainTimeoutError";
  }
}

export interface ProjectedOutputFunctionRequestScope {
  readonly activeOwner: string;
  readonly outputOwner: string;
}

export const projectedOutputFunctionOwner = (
  projectionRevision: string,
  sourceVersion: number | null | "pending",
): string => JSON.stringify([projectionRevision, sourceVersion]);

export interface ProjectedOutputFunctionClient {
  dispose(): void;
}

export interface ProjectedOutputFunctionTransition {
  readonly gate: ProjectedOutputFunctionGate;
  readonly generation: number;
  readonly drained: Promise<void>;
  cancelDrain(): void;
}

interface ActiveClient {
  readonly controller: AbortController;
  readonly owner: symbol;
}

interface ProjectedOutputScope {
  readonly activeOwner: string;
  readonly outputOwner: string;
  readonly wrapper: HTMLElement;
}

interface FunctionScopeWaiter {
  readonly client: symbol;
  readonly element: HTMLElement;
  readonly outputOwner: string;
  readonly reject: (cause: DOMException) => void;
  readonly resolve: () => void;
  readonly wrapper: HTMLElement;
}

export const isProjectedOutputFunctionAbort = (cause: unknown): cause is DOMException =>
  cause instanceof DOMException &&
  cause.name === "AbortError" &&
  cause.message === PROJECTED_OUTPUT_FUNCTION_ABORT_MESSAGE;

const functionScopeAbort = (): DOMException =>
  new DOMException(PROJECTED_OUTPUT_FUNCTION_ABORT_MESSAGE, "AbortError");

type ProjectedOutputFunctionClassifier = <Result>(operation: Promise<Result>) => Promise<Result>;

let projectedOutputFunctionClassifier: ProjectedOutputFunctionClassifier | undefined;

export const classifyProjectedOutputFunctionRequest = <Result>(
  operation: Promise<Result>,
): Promise<Result> => projectedOutputFunctionClassifier?.(operation) ?? operation;

const sendProjectedOutputFunctionRequest = <Result>(
  send: () => Promise<Result>,
  classifier: ProjectedOutputFunctionClassifier,
): Promise<Result> => {
  const previous = projectedOutputFunctionClassifier;
  projectedOutputFunctionClassifier = classifier;
  try {
    return send();
  } finally {
    projectedOutputFunctionClassifier = previous;
  }
};

const closestProjectedOutput = (element: Element): HTMLElement | undefined => {
  let current: Element | null = element;
  while (current) {
    const wrapper = current.closest(`[${PROJECTED_OUTPUT_SCOPE_ATTRIBUTE}]`);
    if (wrapper instanceof HTMLElement) {
      return wrapper;
    }
    const root = current.getRootNode();
    current = root instanceof ShadowRoot ? root.host : null;
  }
  return undefined;
};

const projectedOutputScope = (element: HTMLElement): ProjectedOutputScope | undefined => {
  const wrapper = closestProjectedOutput(element);
  if (!wrapper) {
    return undefined;
  }
  const activeOwner = wrapper.getAttribute(PROJECTED_OUTPUT_ACTIVE_OWNER_ATTRIBUTE);
  const outputOwner = wrapper.getAttribute(PROJECTED_OUTPUT_OWNER_ATTRIBUTE);
  if (!activeOwner || !outputOwner || !wrapper.isConnected) {
    throw functionScopeAbort();
  }
  return { activeOwner, outputOwner, wrapper };
};

const waitForClient = <Result>(
  operation: Promise<Result>,
  signal: AbortSignal,
): Promise<Result> => {
  if (signal.aborted) {
    return Promise.reject(signal.reason ?? functionScopeAbort());
  }
  return new Promise<Result>((resolve, reject) => {
    const cleanup = () => signal.removeEventListener("abort", abort);
    const abort = () => {
      cleanup();
      reject(signal.reason ?? functionScopeAbort());
    };
    signal.addEventListener("abort", abort, { once: true });
    operation.then(
      (result) => {
        cleanup();
        resolve(result);
      },
      (cause) => {
        cleanup();
        reject(cause);
      },
    );
  });
};

export class ProjectedOutputFunctionGate {
  private readonly admissions = new Set<Promise<unknown>>();
  private client: ActiveClient | undefined;
  private disposed = false;
  private observer: MutationObserver | undefined;
  private observedRoots = new WeakSet<Node>();
  private paused = false;
  private transitionGeneration = 0;
  private readonly waiters = new Set<FunctionScopeWaiter>();

  activateClient(): ProjectedOutputFunctionClient {
    if (this.disposed) {
      throw new Error("The projected output function gate has closed.");
    }
    this.releaseClient(this.client?.owner);
    const client = {
      controller: new AbortController(),
      owner: Symbol("projected-output-function-client"),
    };
    this.client = client;
    return { dispose: () => this.releaseClient(client.owner) };
  }

  beginTransition(): ProjectedOutputFunctionTransition {
    this.transitionGeneration += 1;
    this.paused = true;
    const admissions = [...this.admissions];
    let cancelDrain = () => {};
    const drained = new Promise<void>((resolve, reject) => {
      let settled = false;
      const settle = (complete: () => void) => {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timeout);
        complete();
      };
      const timeout = setTimeout(
        () => settle(() => reject(new ProjectedOutputFunctionDrainTimeoutError())),
        PROJECTED_OUTPUT_FUNCTION_DRAIN_TIMEOUT_MS,
      );
      cancelDrain = () => settle(resolve);
      void Promise.allSettled(admissions).then(() => settle(resolve));
    });
    return {
      cancelDrain,
      drained,
      gate: this,
      generation: this.transitionGeneration,
    };
  }

  completeTransition(claim: ProjectedOutputFunctionTransition): void {
    claim.cancelDrain();
    if (claim.gate !== this || claim.generation !== this.transitionGeneration) {
      return;
    }
    this.paused = false;
    this.settleWaiters();
  }

  cancelTransition(claim: ProjectedOutputFunctionTransition): void {
    claim.cancelDrain();
    if (claim.gate !== this || claim.generation !== this.transitionGeneration) {
      return;
    }
    this.paused = true;
    this.releaseClient(this.client?.owner);
  }

  run<Result>(element: HTMLElement, send: () => Promise<Result>): Promise<Result> {
    let scope: ProjectedOutputScope | undefined;
    try {
      scope = projectedOutputScope(element);
    } catch (cause) {
      return Promise.reject(cause);
    }
    if (!scope) {
      try {
        return send();
      } catch (cause) {
        return Promise.reject(cause);
      }
    }
    return this.execute(element, scope.wrapper, scope.outputOwner, send);
  }

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    this.releaseClient(this.client?.owner);
    this.observer?.disconnect();
    this.observer = undefined;
    for (const waiter of this.waiters) {
      waiter.reject(functionScopeAbort());
    }
    this.waiters.clear();
  }

  private execute<Result>(
    element: HTMLElement,
    wrapper: HTMLElement,
    outputOwner: string,
    send: () => Promise<Result>,
  ): Promise<Result> {
    const client = this.client;
    if (this.disposed || !client || client.controller.signal.aborted) {
      return Promise.reject(functionScopeAbort());
    }
    let scope: ProjectedOutputScope | undefined;
    try {
      scope = projectedOutputScope(element);
    } catch (cause) {
      return Promise.reject(cause);
    }
    if (!scope || scope.wrapper !== wrapper || scope.outputOwner !== outputOwner) {
      return Promise.reject(functionScopeAbort());
    }
    if (!this.paused && scope.activeOwner === outputOwner) {
      try {
        const classifier: ProjectedOutputFunctionClassifier = (operation) =>
          this.trackOperation(
            this.trackAdmission(operation),
            client,
            element,
            wrapper,
            outputOwner,
          );
        const operation = sendProjectedOutputFunctionRequest(send, classifier);
        return this.trackOperation(operation, client, element, wrapper, outputOwner);
      } catch (cause) {
        return Promise.reject(cause);
      }
    }
    if (!this.paused) {
      return Promise.reject(functionScopeAbort());
    }
    return this.wait(client.owner, element, wrapper, outputOwner).then(() =>
      this.execute(element, wrapper, outputOwner, send),
    );
  }

  private trackOperation<Result>(
    operation: Promise<Result>,
    client: ActiveClient,
    element: HTMLElement,
    wrapper: HTMLElement,
    outputOwner: string,
  ): Promise<Result> {
    return waitForClient(operation, client.controller.signal).then(
      (result) => this.deliverResult(result, client, element, wrapper, outputOwner),
      (cause: unknown) => this.deliverFailure(cause, client, element, wrapper, outputOwner),
    );
  }

  private trackAdmission<Result>(operation: Promise<Result>): Promise<Result> {
    this.admissions.add(operation);
    void operation.then(
      () => this.admissions.delete(operation),
      () => this.admissions.delete(operation),
    );
    return operation;
  }

  private deliverFailure(
    cause: unknown,
    client: ActiveClient,
    element: HTMLElement,
    wrapper: HTMLElement,
    outputOwner: string,
  ): Promise<never> {
    if (isProjectedOutputFunctionAbort(cause)) {
      return Promise.reject(cause);
    }
    if (this.client?.owner !== client.owner || client.controller.signal.aborted) {
      return Promise.reject(functionScopeAbort());
    }
    let current: ProjectedOutputScope | undefined;
    try {
      current = projectedOutputScope(element);
    } catch {
      return Promise.reject(functionScopeAbort());
    }
    if (!current || current.wrapper !== wrapper || current.outputOwner !== outputOwner) {
      return Promise.reject(functionScopeAbort());
    }
    if (!this.paused) {
      return current.activeOwner === outputOwner
        ? Promise.reject(cause)
        : Promise.reject(functionScopeAbort());
    }
    return this.wait(client.owner, element, wrapper, outputOwner).then(() =>
      this.deliverFailure(cause, client, element, wrapper, outputOwner),
    );
  }

  private deliverResult<Result>(
    result: Result,
    client: ActiveClient,
    element: HTMLElement,
    wrapper: HTMLElement,
    outputOwner: string,
  ): Promise<Result> {
    if (this.client?.owner !== client.owner || client.controller.signal.aborted) {
      return Promise.reject(functionScopeAbort());
    }
    let current: ProjectedOutputScope | undefined;
    try {
      current = projectedOutputScope(element);
    } catch (cause) {
      return Promise.reject(cause);
    }
    if (!current || current.wrapper !== wrapper || current.outputOwner !== outputOwner) {
      return Promise.reject(functionScopeAbort());
    }
    if (!this.paused && current.activeOwner === outputOwner) {
      return Promise.resolve(result);
    }
    if (!this.paused) {
      return Promise.reject(functionScopeAbort());
    }
    return this.wait(client.owner, element, wrapper, outputOwner).then(() =>
      this.deliverResult(result, client, element, wrapper, outputOwner),
    );
  }

  private observe(root: Node): void {
    if (this.observedRoots.has(root)) {
      return;
    }
    this.observer ??= new MutationObserver(() => this.settleWaiters());
    this.observer.observe(root, {
      attributeFilter: [PROJECTED_OUTPUT_ACTIVE_OWNER_ATTRIBUTE, PROJECTED_OUTPUT_OWNER_ATTRIBUTE],
      attributes: true,
      childList: true,
      subtree: true,
    });
    this.observedRoots.add(root);
  }

  private releaseClient(owner: symbol | undefined): void {
    if (!owner || this.client?.owner !== owner) {
      return;
    }
    const client = this.client;
    this.client = undefined;
    client.controller.abort(functionScopeAbort());
    for (const waiter of this.waiters) {
      if (waiter.client === owner) {
        this.waiters.delete(waiter);
        waiter.reject(functionScopeAbort());
      }
    }
    this.stopObservingIfIdle();
  }

  private settleWaiters(): void {
    for (const waiter of this.waiters) {
      if (this.client?.owner !== waiter.client) {
        this.waiters.delete(waiter);
        waiter.reject(functionScopeAbort());
        continue;
      }
      let scope: ProjectedOutputScope | undefined;
      try {
        scope = projectedOutputScope(waiter.element);
      } catch {
        this.waiters.delete(waiter);
        waiter.reject(functionScopeAbort());
        continue;
      }
      if (!scope || scope.wrapper !== waiter.wrapper || scope.outputOwner !== waiter.outputOwner) {
        this.waiters.delete(waiter);
        waiter.reject(functionScopeAbort());
      } else if (!this.paused) {
        this.waiters.delete(waiter);
        if (scope.activeOwner === waiter.outputOwner) {
          waiter.resolve();
        } else {
          waiter.reject(functionScopeAbort());
        }
      }
    }
    this.stopObservingIfIdle();
  }

  private stopObservingIfIdle(): void {
    if (this.waiters.size > 0) {
      return;
    }
    this.observer?.disconnect();
    this.observer = undefined;
    this.observedRoots = new WeakSet();
  }

  private wait(
    client: symbol,
    element: HTMLElement,
    wrapper: HTMLElement,
    outputOwner: string,
  ): Promise<void> {
    this.observe(wrapper.getRootNode());
    return new Promise<void>((resolve, reject) => {
      this.waiters.add({
        client,
        element,
        outputOwner,
        reject,
        resolve,
        wrapper,
      });
    });
  }
}

let activeGate: ProjectedOutputFunctionGate | undefined;

export const startProjectedOutputFunctionGate = (): ProjectedOutputFunctionGate => {
  activeGate?.dispose();
  activeGate = new ProjectedOutputFunctionGate();
  return activeGate;
};

export const disposeProjectedOutputFunctionGate = (gate: ProjectedOutputFunctionGate): void => {
  gate.dispose();
  if (activeGate === gate) {
    activeGate = undefined;
  }
};

export const beginProjectedOutputFunctionTransition = ():
  | ProjectedOutputFunctionTransition
  | undefined => activeGate?.beginTransition();

export const completeProjectedOutputFunctionTransition = (
  claim: ProjectedOutputFunctionTransition | undefined,
): void => claim?.gate.completeTransition(claim);

export const cancelProjectedOutputFunctionTransition = (
  claim: ProjectedOutputFunctionTransition | undefined,
): void => claim?.gate.cancelTransition(claim);

export const cancelProjectedOutputFunctionTransitionDrain = (
  claim: ProjectedOutputFunctionTransition | undefined,
): void => claim?.cancelDrain();

export const runProjectedOutputFunctionRequest = <Result>(
  element: HTMLElement,
  send: () => Promise<Result>,
): Promise<Result> => activeGate?.run(element, send) ?? send();
