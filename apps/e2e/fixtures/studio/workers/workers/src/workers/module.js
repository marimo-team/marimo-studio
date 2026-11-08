import { chunk } from "./module-chunk.js";

const earlyMessage = new Promise((resolve) => {
  self.addEventListener("message", ({ data }) => resolve(data), { once: true });
  setTimeout(resolve, 2000, "");
});

self.postMessage({
  name: self.name,
  location: self.location.href,
  chunk,
  importMeta: import.meta.url,
  earlyMessage: await earlyMessage,
  fetched: await fetch("module-chunk.js").then((response) => response.ok),
});
