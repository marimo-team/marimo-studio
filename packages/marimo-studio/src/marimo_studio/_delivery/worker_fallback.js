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
    const absolute = (url) => URL.parse(url, workerUrl)?.href ?? url;
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
      return dataScript(`import ${JSON.stringify(copy)};`);
    }
    return script;
  };

  const startUrl = (url, requested, options) => {
    const isModule = options?.type === "module";
    if (url?.protocol === "blob:" && isModule && !runsBlobModules) {
      try {
        return blobModule(url.href);
      } catch {
        return requested;
      }
    }
    if (url?.origin === new URL(document.baseURI).origin && /^https?:$/.test(url.protocol)) {
      return dataScript((isModule ? moduleBootstrap : classicBootstrap)(url.href));
    }
    return requested;
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

  // A Proxy keeps `instanceof Worker`, subclassing, and the constructor's name.
  self.Worker = new Proxy(self.Worker, {
    construct(target, [requested, options], newTarget) {
      const url = URL.parse(String(requested), document.baseURI);
      // An opaque origin has no cookies, and the bootstrap's cross-origin import
      // cannot satisfy `credentials: "include"`.
      const worker = Reflect.construct(
        target,
        [startUrl(url, requested, options), { ...options, credentials: "same-origin" }],
        newTarget,
      );
      // A subclass override would run before the subclass's own fields exist.
      EventTarget.prototype.addEventListener.call(worker, "error", (event) =>
        report((url?.href ?? String(requested)).slice(0, 2048), event),
      );
      return worker;
    },
  });
})();
