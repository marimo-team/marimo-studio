importScripts("classic-chunk.js");

fetch("classic-chunk.js")
  .then((response) => response.text())
  .then((text) => {
    const request = new XMLHttpRequest();
    request.open("GET", "classic-chunk.js", false);
    request.send();
    self.postMessage({
      name: self.name,
      location: self.location.href,
      chunk: self.classicChunk,
      fetched: text === request.responseText && text.includes("classicChunk"),
    });
  });
