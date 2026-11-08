const started = (worker) =>
  new Promise((resolve) => {
    worker.addEventListener("message", ({ data }) => {
      resolve({ ...data, instance: worker instanceof Worker });
    });
    worker.addEventListener("error", () => resolve({ failed: true }));
  });

const refused = (url) =>
  new Promise((resolve) => {
    try {
      new Worker(url).addEventListener("error", () => resolve(true));
    } catch {
      resolve(true);
    }
  });

const workerUrl = (path) => new URL(`../workers/${path}`, import.meta.url);
const inlineWorkerUrl = (source) =>
  URL.createObjectURL(new Blob([source], { type: "text/javascript" }));
const pageBlob = URL.createObjectURL(new Blob(["page blob"]));
const inlineSource = `self.postMessage({ name: self.name, source: "inline" });`;

class ListeningWorker extends Worker {
  #listeners = [];

  addEventListener(...listener) {
    this.#listeners.push(listener);
    super.addEventListener(...listener);
  }
}

const earlyMessage = new Worker(workerUrl("module.js"), { name: "module-worker", type: "module" });
const moduleResult = started(earlyMessage);
earlyMessage.postMessage("sent at construction");

globalThis.workerResults = (async () => ({
  origin: globalThis.origin,
  classic: await started(new Worker(workerUrl("classic.js"), { name: "classic-worker" })),
  module: await moduleResult,
  inlineModule: await started(
    new Worker(
      inlineWorkerUrl(
        `self.postMessage({
          name: self.name,
          source: "inline",
          pageBlob: await (await fetch(${JSON.stringify(pageBlob)})).text(),
        });`,
      ),
      { name: "inline-module-worker", type: "module" },
    ),
  ),
  largeInlineModule: await started(
    new Worker(inlineWorkerUrl(`${inlineSource}//${"x".repeat(3 * 1024 * 1024)}`), {
      name: "large-inline-module-worker",
      type: "module",
    }),
  ),
  inlineClassic: await started(
    new Worker(inlineWorkerUrl(inlineSource), { name: "inline-classic-worker" }),
  ),
  failing: await started(new Worker("workers/failing.js")),
  subclass: await started(new ListeningWorker(workerUrl("classic.js"))),
  credentialed: await started(
    new Worker(workerUrl("module.js"), { credentials: "include", type: "module" }),
  ),
  crossOrigin: await refused("http://cross-origin.invalid/worker.js"),
}))();
