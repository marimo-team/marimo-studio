import type {
  BrowserContext,
  ConsoleMessage,
  Frame,
  Page,
  Request,
  Response,
  Worker,
} from "@playwright/test";

import {
  BrowserResponseExpectations,
  type BrowserResponseExpectation,
} from "./browser-response-expectations.ts";
import { shouldRecordConsoleMessage } from "./console-policy.ts";
import { ExactPageRetirementWitness } from "./page-retirement.ts";
import { drainPendingTasks } from "./pending-tasks.ts";
import {
  ProjectionReadRequestWindow,
  projectionReadRequestKind,
  type ProjectionReadSuccessorPolicy,
} from "./projection-read-window.ts";
import { ExactRequestAbortWindow } from "./request-abort-window.ts";
import {
  BrowserRequestOwners,
  ExactRequestAbortWitness,
  IdempotentReadRecovery,
  WorkspaceEventStreamReplacementWindow,
  abortedResponseCompleted,
  requestAbortsRetiredByDocument,
  type BrowserRequestOwner,
} from "./request-identity.ts";
import { ResponseTransitionWindow } from "./response-transition.ts";

export type { BrowserResponseExpectation } from "./browser-response-expectations.ts";

export interface BrowserDiagnostics {
  messages: string[];
  expectConsole(expectation: BrowserConsoleExpectation): BrowserResponseRecovery;
  expectResponse(expectation: BrowserResponseExpectation): BrowserResponseRecovery;
  expectResponseTransition(
    page: Page,
    expectation: BrowserResponseTransitionExpectation,
  ): ResponseTransitionCapture;
  expectFrameRetirement(frame: Frame): BrowserResponseRecovery;
  expectPageRetirement(page: Page): BrowserResponseRecovery;
  expectHeldRequestAbort(request: Request, completion: Promise<void>): HeldRequestAbortCapture;
  expectProjectionRefresh(
    frame: Frame,
    initialProjectionRevision: string,
    successorPolicy?: ProjectionReadSuccessorPolicy,
  ): ProjectionRefreshCapture;
  expectActiveRequestAbort(expectation: BrowserActiveRequestAbortExpectation): RequestAbortCapture;
  expectRequestAbort(expectation: BrowserRequestAbortExpectation): RequestAbortCapture;
  expectRequestFailure(expectation: BrowserRequestFailureExpectation): BrowserResponseRecovery;
  expectWorkspaceEventStreamReplacement(
    eventsUrl: string,
    count?: number,
  ): WorkspaceEventStreamCapture;
}

export interface BrowserDiagnosticsScope extends BrowserDiagnostics {
  close(): Promise<void>;
}

export const expectSupersededRenewalConfig = (
  diagnostics: BrowserDiagnostics,
  view: string,
): BrowserResponseRecovery =>
  diagnostics.expectResponse({
    status: 409,
    path: new RegExp(
      `^/_marimo-studio/presentation/[^/]+/_marimo-studio/views/${view.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/config$`,
    ),
    error: "presentation-revision-unavailable",
    count: 1,
    required: false,
  });

export interface BrowserResponseRecovery {
  recovered(): void;
}

export interface WorkspaceEventStreamCapture extends BrowserResponseRecovery {
  ready(): boolean;
}

export interface ProjectionRefreshCapture {
  dispose(): void;
  ready(currentProjectionRevision: string): boolean;
  recovered(currentProjectionRevision: string): boolean;
  seal(): void;
  terminalizeValues(targets: readonly string[]): void;
}

export interface HeldRequestAbortCapture {
  requestFailed(): Promise<void>;
  recovered(): void;
}

export interface RequestAbortCapture {
  ready(): boolean;
  recovered(): boolean;
  seal(): void;
}

export interface ResponseTransitionCapture {
  ready(): boolean;
  recovered(): boolean;
  seal(): void;
}

export interface BrowserResponseTransitionExpectation {
  origin: string;
  method: string;
  path: RegExp;
  failureStatus: number;
  failureError: string;
  successStatus: number;
}

interface BrowserRequestMatcher {
  origin: string;
  path: RegExp;
  method: string;
  count?: number;
}

export interface BrowserRequestAbortExpectation extends BrowserRequestMatcher {
  required?: boolean;
  status?: number;
}

export interface BrowserActiveRequestAbortExpectation extends BrowserRequestMatcher {
  required?: boolean;
  status?: number;
}

export interface BrowserRequestFailureExpectation extends BrowserRequestMatcher {
  errorText: string;
  required?: boolean;
}

export interface BrowserConsoleExpectation {
  type?: "warning" | "error";
  text: RegExp;
  count?: number;
  required?: boolean;
}

interface TrackedBrowserConsole extends BrowserConsoleExpectation {
  seen: number;
  isRecovered: boolean;
}

interface TrackedRequestFailure extends BrowserRequestFailureExpectation {
  seen: number;
  isRecovered: boolean;
}

interface TrackedFrameRetirement {
  invalidRecovery: boolean;
  isRecovered: boolean;
  seen: number;
}

interface PendingRequestAbort {
  owner: BrowserRequestOwner;
  request: Request;
  start: number | undefined;
  url: string;
}

interface PageDiagnostics {
  captureRequestAbortWindow(window: ExactRequestAbortWindow<Request>): void;
  captureWorkspaceEventStream(window: WorkspaceEventStreamReplacementWindow): void;
  pendingRequestAborts: Set<PendingRequestAbort>;
  expectFrameRetirement(frame: Frame): BrowserResponseRecovery;
  expectPageRetirement(): BrowserResponseRecovery;
  expectResponseTransition(
    expectation: BrowserResponseTransitionExpectation,
  ): ResponseTransitionCapture;
  expectProjectionRefresh(
    frame: Frame,
    initialProjectionRevision: string,
    successorPolicy?: ProjectionReadSuccessorPolicy,
  ): ProjectionRefreshCapture;
  frameRetirements: Set<TrackedFrameRetirement>;
  pageRetirements: Set<ExactPageRetirementWitness<BrowserRequestOwner>>;
  projectionReadWindows: Set<ProjectionReadRequestWindow>;
  responseTransitions: Set<ResponseTransitionWindow<Request, BrowserRequestOwner>>;
  dispose(): void;
}

const expectedCardinality = (count: number | undefined): number => {
  const cardinality = count ?? 1;
  if (!Number.isSafeInteger(cardinality) || cardinality < 1) {
    throw new RangeError("Browser diagnostic expectations require a positive count.");
  }
  return cardinality;
};

const observePageDiagnostics = (
  page: Page,
  messages: string[],
  pendingResponses: Set<Promise<void>>,
  expectedConsole: TrackedBrowserConsole[],
  expectedResponses: BrowserResponseExpectations,
  expectedHeldRequestAborts: Map<Request, ExactRequestAbortWitness<Request>>,
  expectedRequestAborts: Set<ExactRequestAbortWindow<Request>>,
  futureRequestAborts: Set<ExactRequestAbortWindow<Request>>,
  expectedRequestFailures: TrackedRequestFailure[],
  workspaceEventStreamReplacements: Set<WorkspaceEventStreamReplacementWindow>,
): PageDiagnostics => {
  const activeRequests = new Set<Request>();
  let nextOwnerId = 0;
  const createOwner = (): BrowserRequestOwner => ({ id: ++nextOwnerId });
  const frameLessOwner = createOwner();
  const sourceOwners = new BrowserRequestOwners<Frame | Worker>(createOwner);
  const requestOwners = new WeakMap<Request, BrowserRequestOwner>();
  const requestStarts = new WeakMap<Request, number>();
  let nextRequestStart = 0;
  const pendingRequestAborts = new Set<PendingRequestAbort>();
  const frameRetirementsByOwner = new Map<BrowserRequestOwner, TrackedFrameRetirement>();
  const frameRetirements = new Set<TrackedFrameRetirement>();
  const pageRetirements = new Set<ExactPageRetirementWitness<BrowserRequestOwner>>();
  const pageRetirementCleanups = new Map<
    ExactPageRetirementWitness<BrowserRequestOwner>,
    () => void
  >();
  let activePageRetirement: ExactPageRetirementWitness<BrowserRequestOwner> | undefined;
  const requestRecovery = new IdempotentReadRecovery();
  const projectionReadWindows = new Set<ProjectionReadRequestWindow>();
  const responseTransitions = new Set<ResponseTransitionWindow<Request, BrowserRequestOwner>>();
  const responseStatuses = new WeakMap<Request, number>();
  const responseErrors = new WeakMap<Request, string | undefined>();
  const finishedRequests = new WeakSet<Request>();
  const requestOwner = (request: Request) => {
    const serviceWorker = request.serviceWorker();
    if (serviceWorker !== null) {
      return sourceOwners.ownerFor(serviceWorker);
    }
    try {
      return sourceOwners.ownerFor(request.frame());
    } catch {
      return frameLessOwner;
    }
  };
  const onRequest = (request: Request) => {
    activeRequests.add(request);
    const owner = requestOwner(request);
    const start = ++nextRequestStart;
    requestOwners.set(request, owner);
    requestStarts.set(request, start);
    activePageRetirement?.recordOwner(owner);
    responseTransitions.forEach((window) => window.recordStart(request, owner, start));
    futureRequestAborts.forEach((window) => window.recordStart(request));
    projectionReadWindows.forEach((window) => window.recordStart(request, owner, start));
    workspaceEventStreamReplacements.forEach((window) => window.recordStart(request, owner));
    if (projectionReadRequestKind(request) === undefined) {
      requestRecovery.recordStart(request, owner);
    }
  };
  const onPageError = (error: Error) => messages.push(`pageerror: ${error.message}`);
  const terminalizeSpecializedRequest = (request: Request) => {
    projectionReadWindows.forEach((window) => window.recordFailure(request));
    workspaceEventStreamReplacements.forEach((window) => window.recordFailure(request));
  };
  const terminalizeRequest = (request: Request) => {
    requestRecovery.recordFailure(request);
    terminalizeSpecializedRequest(request);
  };
  const onConsole = (message: ConsoleMessage) => {
    const expected = expectedConsole.find((item) => {
      item.text.lastIndex = 0;
      return (
        !item.isRecovered &&
        item.seen < expectedCardinality(item.count) &&
        (item.type === undefined || item.type === message.type()) &&
        item.text.test(message.text())
      );
    });
    if (expected) {
      expected.seen += 1;
      return;
    }
    if (shouldRecordConsoleMessage(message.type(), message.text())) {
      const source = message.location().url;
      messages.push(`console${source ? ` (${source})` : ""}: ${message.text()}`);
    }
  };
  const onRequestFailed = (request: Request) => {
    activeRequests.delete(request);
    responseTransitions.forEach((window) => window.recordTerminal(request));
    const failure = request.failure()?.errorText ?? "unknown error";
    const url = new URL(request.url());
    const exactAbort = expectedHeldRequestAborts.get(request);
    if (exactAbort?.recordFailure(request, failure)) {
      terminalizeRequest(request);
      return;
    }
    let expectedAbort = false;
    expectedRequestAborts.forEach((window) => {
      expectedAbort = window.recordAbort(request, failure) || expectedAbort;
    });
    if (expectedAbort) {
      terminalizeRequest(request);
      return;
    }
    if (failure !== "net::ERR_ABORTED") {
      expectedRequestAborts.forEach((window) => window.recordTerminal(request));
    }
    const owner = requestOwners.get(request) ?? requestOwner(request);
    if (activePageRetirement?.recordAbort(owner, failure)) {
      requestRecovery.recordFailure(request);
      projectionReadWindows.forEach((window) => window.recordFailure(request));
      return;
    }
    const frameRetirement = frameRetirementsByOwner.get(owner);
    if (failure === "net::ERR_ABORTED" && frameRetirement !== undefined) {
      requestRecovery.recordFailure(request);
      projectionReadWindows.forEach((window) => window.recordFailure(request));
      frameRetirement.seen += 1;
      return;
    }
    if (failure === "net::ERR_ABORTED") {
      let captured = false;
      projectionReadWindows.forEach((window) => {
        captured = window.recordAbort(request) || captured;
      });
      workspaceEventStreamReplacements.forEach((window) => {
        captured = window.recordAbort(request) || captured;
      });
      if (captured) {
        terminalizeRequest(request);
        return;
      }
    }
    const expectedFailure = expectedRequestFailures.find((item) => {
      item.path.lastIndex = 0;
      return (
        !item.isRecovered &&
        item.seen < expectedCardinality(item.count) &&
        item.errorText === failure &&
        new URL(item.origin).origin === url.origin &&
        (item.method === undefined || item.method === request.method()) &&
        item.path.test(url.pathname)
      );
    });
    if (expectedFailure) {
      terminalizeRequest(request);
      expectedFailure.seen += 1;
      return;
    }
    terminalizeSpecializedRequest(request);
    if (failure === "net::ERR_ABORTED" && requestRecovery.recordAbort(request)) {
      return;
    }
    if (failure === "net::ERR_ABORTED") {
      const pendingAbort = {
        owner,
        request,
        start: requestRecovery.startOrdinal(request),
        url: request.url(),
      };
      pendingRequestAborts.add(pendingAbort);
      let inspection: Promise<void>;
      inspection = request
        .response()
        .then((response) => {
          const status = response?.status();
          if (abortedResponseCompleted(request, status, finishedRequests.has(request))) {
            pendingRequestAborts.delete(pendingAbort);
            requestRecovery.discardAbort(request);
          }
        })
        .catch(() => {})
        .finally(() => pendingResponses.delete(inspection));
      pendingResponses.add(inspection);
      return;
    }
    requestRecovery.recordFailure(request);
    messages.push(`request failed: ${request.url()} (${failure})`);
  };
  const onRequestFinished = (request: Request) => {
    finishedRequests.add(request);
    activeRequests.delete(request);
    responseTransitions.forEach((window) => window.recordTerminal(request));
    expectedRequestAborts.forEach((window) => window.recordTerminal(request));
    const status = responseStatuses.get(request);
    if (status === undefined) {
      requestRecovery.recordFailure(request);
      projectionReadWindows.forEach((window) => window.recordFailure(request));
      workspaceEventStreamReplacements.forEach((window) => window.recordFailure(request));
      return;
    }
    const owner = requestOwners.get(request) ?? frameLessOwner;
    const start = requestStarts.get(request) ?? 0;
    projectionReadWindows.forEach((window) => window.recordResponse(request, owner, start, status));
    if (status >= 400) {
      requestRecovery.recordFailure(request);
      workspaceEventStreamReplacements.forEach((window) => window.recordFailure(request));
      return;
    }
    const recoveredStart = requestRecovery.recordSuccess(request);
    if (recoveredStart !== undefined) {
      const recovered = Array.from(pendingRequestAborts).find(
        (item) => item.start === recoveredStart,
      );
      if (recovered !== undefined) {
        pendingRequestAborts.delete(recovered);
      }
    }
    if (request.resourceType() === "document") {
      for (const retired of requestAbortsRetiredByDocument(pendingRequestAborts, owner, start)) {
        pendingRequestAborts.delete(retired);
        requestRecovery.discardAbort(retired.request);
      }
    }
  };
  const onResponse = (response: Response) => {
    responseStatuses.set(response.request(), response.status());
    const responseError = response.headers()["marimo-studio-error"];
    responseErrors.set(response.request(), responseError);
    expectedRequestAborts.forEach((window) =>
      window.recordResponse(response.request(), response.status()),
    );
    workspaceEventStreamReplacements.forEach((window) =>
      window.recordResponse(response.request(), response.status()),
    );
    let capturedTransition = false;
    responseTransitions.forEach((window) => {
      capturedTransition =
        window.recordResponse(response.request(), response.status(), responseError) ||
        capturedTransition;
    });
    if (capturedTransition) {
      return;
    }
    let task: Promise<void>;
    task = expectedResponses
      .inspect(response)
      .then((diagnostic) => {
        if (diagnostic !== undefined) {
          messages.push(diagnostic);
        }
      })
      .catch(() => {
        messages.push("response inspection failed");
      })
      .finally(() => pendingResponses.delete(task));
    pendingResponses.add(task);
  };
  page.on("request", onRequest);
  page.on("pageerror", onPageError);
  page.on("console", onConsole);
  page.on("requestfailed", onRequestFailed);
  page.on("requestfinished", onRequestFinished);
  page.on("response", onResponse);
  return {
    captureRequestAbortWindow: (window) => {
      activeRequests.forEach((request) =>
        window.recordActive(request, responseStatuses.get(request)),
      );
    },
    captureWorkspaceEventStream: (window) => {
      activeRequests.forEach((request) => {
        const owner = requestOwners.get(request) ?? frameLessOwner;
        if (window.recordStart(request, owner)) {
          const status = responseStatuses.get(request);
          if (status !== undefined) {
            window.recordResponse(request, status);
          }
        }
      });
    },
    pendingRequestAborts,
    frameRetirements,
    pageRetirements,
    projectionReadWindows,
    responseTransitions,
    expectFrameRetirement: (frame) => {
      if (frame.isDetached()) {
        throw new Error("The retiring frame has already detached.");
      }
      const owner = sourceOwners.ownerFor(frame);
      const retirement: TrackedFrameRetirement = {
        invalidRecovery: false,
        isRecovered: false,
        seen: 0,
      };
      frameRetirements.add(retirement);
      frameRetirementsByOwner.set(owner, retirement);
      return {
        recovered: () => {
          if (!frame.isDetached()) {
            retirement.invalidRecovery = true;
            return;
          }
          workspaceEventStreamReplacements.forEach((window) => window.retireOwner(owner));
          retirement.isRecovered = true;
        },
      };
    },
    expectPageRetirement: () => {
      if (page.isClosed()) {
        throw new Error("The retiring page has already closed.");
      }
      if (activePageRetirement !== undefined) {
        throw new Error("The page already has a retirement witness.");
      }
      const retirement = new ExactPageRetirementWitness<BrowserRequestOwner>();
      activePageRetirement = retirement;
      pageRetirements.add(retirement);
      page.frames().forEach((frame) => retirement.recordOwner(sourceOwners.ownerFor(frame)));
      activeRequests.forEach((request) => {
        retirement.recordOwner(requestOwners.get(request) ?? frameLessOwner);
      });
      const closed = () => retirement.recordClosed();
      page.once("close", closed);
      const stop = () => page.off("close", closed);
      pageRetirementCleanups.set(retirement, stop);
      return {
        recovered: () => {
          stop();
          pageRetirementCleanups.delete(retirement);
          if (retirement.recover(page.isClosed())) {
            retirement.owned().forEach((owner) => {
              workspaceEventStreamReplacements.forEach((window) => window.retireOwner(owner));
            });
          }
        },
      };
    },
    expectResponseTransition: (expectation) => {
      const window = new ResponseTransitionWindow<Request, BrowserRequestOwner>(
        expectation.origin,
        expectation.method,
        expectation.path,
        expectation.failureStatus,
        expectation.failureError,
        expectation.successStatus,
      );
      responseTransitions.add(window);
      activeRequests.forEach((request) => {
        const owner = requestOwners.get(request) ?? frameLessOwner;
        const start = requestStarts.get(request) ?? 0;
        if (window.recordStart(request, owner, start)) {
          const status = responseStatuses.get(request);
          if (status !== undefined) {
            window.recordResponse(request, status, responseErrors.get(request));
          }
        }
      });
      return {
        ready: () => window.readyToRecover(),
        recovered: () => window.recover(),
        seal: () => window.seal(),
      };
    },
    expectProjectionRefresh: (frame, initialProjectionRevision, successorPolicy = "exact") => {
      if (frame.isDetached()) {
        throw new Error("The projection frame has already detached.");
      }
      const owner = sourceOwners.ownerFor(frame);
      const window = new ProjectionReadRequestWindow(
        owner,
        initialProjectionRevision,
        512,
        successorPolicy,
      );
      projectionReadWindows.add(window);
      activeRequests.forEach((request) => {
        const requestOwner = requestOwners.get(request) ?? frameLessOwner;
        const start = requestStarts.get(request) ?? 0;
        window.recordStart(request, requestOwner, start);
      });
      return {
        dispose: () => window.dispose(),
        recovered: (currentProjectionRevision) => {
          return window.recover(currentProjectionRevision);
        },
        ready: (currentProjectionRevision) => window.readyToRecover(currentProjectionRevision),
        seal: () => window.seal(),
        terminalizeValues: (targets) => {
          window.terminalizeValues(targets);
        },
      };
    },
    dispose: () => {
      page.off("request", onRequest);
      page.off("pageerror", onPageError);
      page.off("console", onConsole);
      page.off("requestfailed", onRequestFailed);
      page.off("requestfinished", onRequestFinished);
      page.off("response", onResponse);
      activeRequests.forEach((request) => {
        requestRecovery.recordFailure(request);
      });
      activeRequests.clear();
      requestRecovery.dispose();
      projectionReadWindows.forEach((window) => window.dispose());
      frameRetirementsByOwner.clear();
      pageRetirementCleanups.forEach((stop) => stop());
      pageRetirementCleanups.clear();
      activePageRetirement = undefined;
    },
  };
};

export const observeBrowserContext = (context: BrowserContext): BrowserDiagnosticsScope => {
  const messages: string[] = [];
  const pendingResponses = new Set<Promise<void>>();
  const expectedConsole: TrackedBrowserConsole[] = [];
  const expectedResponses = new BrowserResponseExpectations();
  const expectedHeldRequestAborts = new Map<Request, ExactRequestAbortWitness<Request>>();
  const expectedRequestAborts = new Set<ExactRequestAbortWindow<Request>>();
  const futureRequestAborts = new Set<ExactRequestAbortWindow<Request>>();
  const expectedRequestFailures: TrackedRequestFailure[] = [];
  const workspaceEventStreamReplacements = new Set<WorkspaceEventStreamReplacementWindow>();
  const pages = new Map<Page, PageDiagnostics>();
  const observe = (page: Page): void => {
    if (pages.has(page)) return;
    pages.set(
      page,
      observePageDiagnostics(
        page,
        messages,
        pendingResponses,
        expectedConsole,
        expectedResponses,
        expectedHeldRequestAborts,
        expectedRequestAborts,
        futureRequestAborts,
        expectedRequestFailures,
        workspaceEventStreamReplacements,
      ),
    );
  };
  context.pages().forEach(observe);
  context.on("page", observe);
  return {
    messages,
    expectConsole: (expectation) => {
      expectedCardinality(expectation.count);
      const tracked: TrackedBrowserConsole = {
        ...expectation,
        seen: 0,
        isRecovered: false,
      };
      expectedConsole.push(tracked);
      return {
        recovered: () => {
          tracked.isRecovered = true;
        },
      };
    },
    expectResponse: (expectation) => {
      const recovered = expectedResponses.expect(expectation);
      return {
        recovered,
      };
    },
    expectResponseTransition: (page, expectation) => {
      const diagnostics = pages.get(page);
      if (diagnostics === undefined) {
        throw new Error("The response transition page is not observed by this browser context.");
      }
      return diagnostics.expectResponseTransition(expectation);
    },
    expectFrameRetirement: (frame) => {
      const diagnostics = pages.get(frame.page());
      if (diagnostics === undefined) {
        throw new Error("The retiring frame is not observed by this browser context.");
      }
      return diagnostics.expectFrameRetirement(frame);
    },
    expectPageRetirement: (page) => {
      const diagnostics = pages.get(page);
      if (diagnostics === undefined) {
        throw new Error("The retiring page is not observed by this browser context.");
      }
      return diagnostics.expectPageRetirement();
    },
    expectHeldRequestAbort: (request, completion) => {
      if (expectedHeldRequestAborts.has(request)) {
        throw new Error("The held request already has an abort witness.");
      }
      const witness = new ExactRequestAbortWitness(request, completion);
      expectedHeldRequestAborts.set(request, witness);
      return {
        requestFailed: () => witness.waitForAbort(),
        recovered: () => witness.recover(),
      };
    },
    expectProjectionRefresh: (frame, initialProjectionRevision, successorPolicy) => {
      const diagnostics = pages.get(frame.page());
      if (diagnostics === undefined) {
        throw new Error("The projection frame is not observed by this browser context.");
      }
      return diagnostics.expectProjectionRefresh(frame, initialProjectionRevision, successorPolicy);
    },
    expectActiveRequestAbort: (expectation) => {
      const window = new ExactRequestAbortWindow<Request>(
        expectation.method,
        expectation.origin,
        expectation.path,
        expectation.count,
        expectation.required ?? false,
        expectation.status,
      );
      expectedRequestAborts.add(window);
      pages.forEach((page) => page.captureRequestAbortWindow(window));
      window.seal();
      return {
        ready: () => window.readyToRecover(),
        recovered: () => window.recover(),
        seal: () => window.seal(),
      };
    },
    expectRequestAbort: (expectation) => {
      const window = new ExactRequestAbortWindow<Request>(
        expectation.method,
        expectation.origin,
        expectation.path,
        expectation.count,
        expectation.required ?? true,
        expectation.status,
      );
      expectedRequestAborts.add(window);
      futureRequestAborts.add(window);
      pages.forEach((page) => page.captureRequestAbortWindow(window));
      return {
        ready: () => window.readyToRecover(),
        recovered: () => window.recover(),
        seal: () => {
          futureRequestAborts.delete(window);
          window.seal();
        },
      };
    },
    expectRequestFailure: (expectation) => {
      expectedCardinality(expectation.count);
      const tracked: TrackedRequestFailure = {
        ...expectation,
        origin: new URL(expectation.origin).origin,
        seen: 0,
        isRecovered: false,
      };
      expectedRequestFailures.push(tracked);
      return {
        recovered: () => {
          tracked.isRecovered = true;
        },
      };
    },
    expectWorkspaceEventStreamReplacement: (eventsUrl, count) => {
      const replacement = new WorkspaceEventStreamReplacementWindow(eventsUrl, count);
      workspaceEventStreamReplacements.add(replacement);
      pages.forEach((page) => page.captureWorkspaceEventStream(replacement));
      return {
        ready: () => replacement.readyToRecover(),
        recovered: () => {
          replacement.recover();
        },
      };
    },
    close: async () => {
      context.off("page", observe);
      const observedPages = [...pages.values()];
      for (const observed of observedPages) {
        observed.dispose();
      }
      pages.clear();
      await drainPendingTasks(pendingResponses);
      for (const observed of observedPages) {
        observed.pendingRequestAborts.forEach((request) => {
          messages.push(`request failed: ${request.url} (net::ERR_ABORTED)`);
        });
        observed.pendingRequestAborts.clear();
        for (const retirement of observed.frameRetirements) {
          if (retirement.invalidRecovery) {
            messages.push("expected frame retirement recovered before the frame detached");
          } else if (retirement.seen > 0 && !retirement.isRecovered) {
            messages.push("expected frame retirement had no observed recovery");
          }
        }
        observed.frameRetirements.clear();
        observed.pageRetirements.forEach((retirement) => {
          messages.push(...retirement.diagnostics());
        });
        observed.pageRetirements.clear();
        observed.projectionReadWindows.forEach((window) => {
          messages.push(...window.diagnostics());
        });
        observed.projectionReadWindows.clear();
        observed.responseTransitions.forEach((window) => {
          messages.push(...window.diagnostics());
        });
        observed.responseTransitions.clear();
      }
      expectedHeldRequestAborts.forEach((witness) => {
        messages.push(...witness.diagnostics());
      });
      expectedHeldRequestAborts.clear();
      expectedRequestAborts.forEach((window) => {
        messages.push(...window.diagnostics());
      });
      expectedRequestAborts.clear();
      futureRequestAborts.clear();
      workspaceEventStreamReplacements.forEach((replacement) => {
        messages.push(...replacement.diagnostics());
      });
      workspaceEventStreamReplacements.clear();
      for (const item of expectedConsole) {
        const cardinality = expectedCardinality(item.count);
        if (item.required !== false && item.seen !== cardinality) {
          messages.push(
            `expected console ${item.type ?? "warning/error"} ${item.text} exactly ${cardinality} time(s), saw ${item.seen}`,
          );
        }
        if (item.seen > 0 && !item.isRecovered) {
          messages.push(
            `expected console ${item.type ?? "warning/error"} ${item.text} did not recover`,
          );
        }
      }
      messages.push(...expectedResponses.diagnostics());
      for (const request of expectedRequestFailures) {
        const cardinality = expectedCardinality(request.count);
        if (request.required !== false && request.seen !== cardinality) {
          messages.push(
            `expected failed requests ${request.path} (${request.errorText}) exactly ${cardinality} time(s), saw ${request.seen}`,
          );
        }
        if (request.seen > 0 && !request.isRecovered) {
          messages.push(
            `expected failed requests ${request.path} (${request.errorText}) had no observed recovery`,
          );
        }
      }
    },
  };
};
