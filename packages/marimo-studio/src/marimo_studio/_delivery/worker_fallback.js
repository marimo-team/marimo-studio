// Starts workers inside an opaque-origin frame. Browsers refuse a worker from an
// http(s) URL there, and Chromium also refuses a blob: module. This runs before
// authored scripts, because ES imports construct workers before a page's own
// code could patch Worker. Same-origin http(s) workers are always rewritten:
// WebKit reports the refusal through an `error` event, so a thrown error cannot
// select the ones that need help.
(() => {
  if (self.origin !== "null") {
    return;
  }

  const dataScript = (source) => `data:text/javascript;charset=utf-8,${encodeURIComponent(source)}`;

  // Serialized into the worker. A data: worker has a data: location, so relative
  // URLs need the worker's real address as their base.
  const rebaseWorkerUrls = (workerUrl) => {
    const absolute = (url) => {
      try {
        return new URL(url, workerUrl).href;
      } catch {
        return url;
      }
    };
    Object.defineProperty(self, "location", {
      configurable: true,
      enumerable: true,
      value: new URL(workerUrl),
    });
    const nativeFetch = self.fetch.bind(self);
    const nativeImportScripts = self.importScripts.bind(self);
    self.fetch = (input, init) =>
      nativeFetch(input instanceof Request ? input : absolute(input), init);
    self.importScripts = (...urls) => nativeImportScripts(...urls.map(absolute));
    self.XMLHttpRequest = class XMLHttpRequest extends self.XMLHttpRequest {
      open(method, url, ...rest) {
        super.open(method, absolute(url), ...rest);
      }
    };
  };

  const rebase = (url) => `(${String(rebaseWorkerUrls)})(${JSON.stringify(url)});`;

  // Static imports evaluate in order, so the rebase finishes before the worker
  // module starts, and page messages reach the module's own listeners.
  const moduleBootstrap = (url) =>
    `import ${JSON.stringify(dataScript(rebase(url)))};import ${JSON.stringify(url)};`;

  const classicBootstrap = (url) => `${rebase(url)}importScripts(${JSON.stringify(url)});`;

  const blobSource = (url) => {
    const request = new XMLHttpRequest();
    request.open("GET", url, false);
    request.send();
    return request.responseText;
  };

  // WebKit runs blob: modules natively, and a data: worker there cannot read the
  // page's blobs.
  const runsBlobModules =
    /AppleWebKit/.test(navigator.userAgent) && !/Chrome\//.test(navigator.userAgent);

  // Chromium caps a worker's URL at 2 MiB. Larger source runs from a private
  // copy of the blob, which outlives a wrapper that revokes its own URL at once.
  const blobModule = (url) => {
    const source = blobSource(url);
    const script = dataScript(source);
    if (script.length > 2 * 1024 * 1024) {
      const copy = URL.createObjectURL(new Blob([source], { type: "text/javascript" }));
      return { script: dataScript(`import ${JSON.stringify(copy)};`), copy };
    }
    return { script };
  };

  const start = (url, requested, type) => {
    const isModule = type === "module";
    if (url?.protocol === "blob:" && isModule && !runsBlobModules) {
      try {
        return blobModule(url.href);
      } catch {
        return { script: requested };
      }
    }
    if (url?.origin === new URL(document.baseURI).origin && /^https?:$/.test(url.protocol)) {
      return { script: dataScript((isModule ? moduleBootstrap : classicBootstrap)(url.href)) };
    }
    return { script: requested };
  };

  const listen = (worker, type, listener, options) => {
    EventTarget.prototype.addEventListener.call(worker, type, listener, options);
  };

  // The worker's asynchronous import needs the copy, and only this page can
  // revoke it. A first message proves the module loaded.
  const releaseCopyWith = (worker, copy) => {
    const release = () => URL.revokeObjectURL(copy);
    listen(worker, "message", release, { once: true });
    listen(worker, "error", release, { once: true });
    worker.terminate = () => {
      release();
      Object.getPrototypeOf(worker).terminate.call(worker);
    };
  };

  // view-script-errors.ts drains this array when the runtime starts and replaces
  // it with a live sink. A worker failing in a loop reports each distinct
  // message once.
  self.__MARIMO_STUDIO_WORKER_ERRORS__ = [];
  const reported = new Set();
  const report = (url, event) => {
    const message = event.message ?? "";
    const key = `${url}\0${message}`;
    if (!reported.has(key) && reported.size !== 16) {
      reported.add(key);
      self.__MARIMO_STUDIO_WORKER_ERRORS__.push({ url, message });
    }
  };

  const parsed = (requested) => {
    try {
      return new URL(String(requested), document.baseURI);
    } catch {
      return null;
    }
  };

  // A Proxy keeps `instanceof Worker`, subclassing, and the constructor's name.
  self.Worker = new Proxy(self.Worker, {
    construct(target, [requested, options], newTarget) {
      const url = parsed(requested);
      const { type, name } = options ?? {};
      const { script, copy } = start(url, requested, type);
      // An opaque origin has no cookies, and the bootstrap's cross-origin import
      // cannot satisfy `credentials: "include"`.
      const worker = Reflect.construct(
        target,
        [script, { type, name, credentials: "same-origin" }],
        newTarget,
      );
      if (copy) {
        releaseCopyWith(worker, copy);
      }
      // A subclass override would run before the subclass's own fields exist.
      listen(worker, "error", (event) =>
        report((url?.href ?? String(requested)).slice(0, 2048), event),
      );
      return worker;
    },
  });
})();
