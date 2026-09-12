export function createStudioDocumentTransactions({ takeChanges, sendTransaction }) {
  let generation = 0;
  let admittedGeneration = 0;
  let operationSequence = 0;
  let pendingGeneration = 0;
  let pendingOperation;
  let retryChanges;
  let admission;
  let draining;

  function hasBridge() {
    try {
      return (
        globalThis.frameElement !== null &&
        globalThis.frameElement.hasAttribute("data-marimo-studio-document-mutation-bridge")
      );
    } catch {
      return false;
    }
  }

  function report(type, details) {
    if (!hasBridge()) return;
    try {
      globalThis.parent.postMessage({ schema: 1, type, ...details }, globalThis.location.origin);
    } catch {
      // The editor may unload after the server has accepted the operation.
    }
  }

  function reportSave(capturedGeneration, succeeded) {
    if (capturedGeneration === 0) return;
    report(
      succeeded
        ? "marimo-studio:editor-document-saved"
        : "marimo-studio:editor-document-save-failed",
      { generation: capturedGeneration },
    );
  }

  function announceMutation(capturedGeneration) {
    if (!hasBridge()) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const channel = new MessageChannel();
      let settled = false;
      const settle = (complete, value) => {
        if (settled) return;
        settled = true;
        clearTimeout(timeout);
        globalThis.removeEventListener("pagehide", onPageHide);
        channel.port1.onmessage = null;
        channel.port1.onmessageerror = null;
        channel.port1.close();
        complete(value);
      };
      const onPageHide = () =>
        settle(reject, new DOMException("The Studio document barrier closed.", "AbortError"));
      const timeout = setTimeout(
        () =>
          settle(
            reject,
            new DOMException("Studio did not acknowledge the document change.", "TimeoutError"),
          ),
        5_000,
      );
      channel.port1.onmessage = ({ data }) => {
        if (!data || data.schema !== 1) return;
        if (
          data.type === "marimo-studio:editor-document-mutation-ready" &&
          data.generation === capturedGeneration
        ) {
          settle(resolve);
        } else if (data.type === "marimo-studio:editor-document-mutation-failed") {
          settle(
            reject,
            new DOMException("Studio could not pause the presentation.", "AbortError"),
          );
        }
      };
      channel.port1.onmessageerror = () =>
        settle(
          reject,
          new DOMException("Studio rejected the document change acknowledgement.", "DataError"),
        );
      channel.port1.start();
      globalThis.addEventListener("pagehide", onPageHide, { once: true });
      try {
        globalThis.parent.postMessage(
          {
            schema: 1,
            type: "marimo-studio:editor-document-mutation",
            generation: capturedGeneration,
          },
          globalThis.location.origin,
          [channel.port2],
        );
      } catch (error) {
        channel.port2.close();
        settle(reject, error);
      }
    });
  }

  function awaitMutation() {
    const capturedGeneration = generation;
    if (capturedGeneration === admittedGeneration) return Promise.resolve();
    if (admission) return admission;
    const pending = announceMutation(capturedGeneration).then(() => {
      if (capturedGeneration === generation) admittedGeneration = capturedGeneration;
    });
    admission = pending;
    const release = () => {
      if (admission === pending) admission = undefined;
    };
    pending.then(release, release);
    return pending;
  }

  async function drain() {
    for (;;) {
      const changes = retryChanges ?? takeChanges();
      retryChanges = undefined;
      if (changes.length === 0) return null;
      try {
        if (pendingGeneration === 0) {
          generation += 1;
          pendingGeneration = generation;
        }
        // A lost response retains the operation identity for the exact retry batch.
        pendingOperation ??=
          Array.from(crypto.getRandomValues(new Uint32Array(4)), (value) =>
            value.toString(36).padStart(7, "0"),
          ).join("") +
          "-" +
          (++operationSequence).toString(36).padStart(7, "0");
        await awaitMutation();
        const changed = await sendTransaction({ changes, studioOperationId: pendingOperation });
        if (changed !== true && changed !== false) {
          throw new Error("Studio document transaction evidence is unavailable");
        }
        report("marimo-studio:editor-document-transaction-applied", {
          generation: pendingGeneration,
          changed,
        });
      } catch (error) {
        report("marimo-studio:editor-document-transaction-failed", {
          generation: pendingGeneration,
        });
        admittedGeneration = Math.max(0, pendingGeneration - 1);
        admission = undefined;
        retryChanges = changes;
        throw error;
      }
      pendingGeneration = 0;
      pendingOperation = undefined;
    }
  }

  function flush() {
    if (draining) return draining;
    const pending = drain();
    draining = pending;
    const release = () => {
      if (draining === pending) draining = undefined;
    };
    pending.then(release, release);
    return pending;
  }

  return { awaitMutation, flush, generation: () => generation, reportSave };
}

export function createStudioDocumentRequests(document, network) {
  return {
    async sendDocumentTransaction(request) {
      await network.waitForConnection();
      const result = await network.post("/api/document/transaction", {
        body: { changes: request.changes },
        headers: { "Marimo-Studio-Document-Operation": request.studioOperationId },
        params: network.params(),
      });
      await network.handleResponse(result);
      const changed = result.response.headers.get("marimo-studio-document-changed");
      if (changed === "true") return true;
      if (changed === "false") return false;
      throw new Error("Studio document transaction evidence is unavailable");
    },
    async sendSave(request) {
      await document.flushBeforeSave();
      const generation = document.generation();
      try {
        const result = await network
          .post("/api/kernel/save", {
            body: request,
            parseAs: "text",
            params: network.params(),
          })
          .then(network.handleResponse);
        document.reportSave(generation, true);
        return result;
      } catch (error) {
        document.reportSave(generation, false);
        throw error;
      }
    },
    async sendRun(request) {
      await network.waitForConnection();
      await document.flush();
      await document.awaitMutation();
      return network
        .post("/api/kernel/run", {
          body: request,
          params: network.params(),
        })
        .then(network.handleResponse);
    },
  };
}
