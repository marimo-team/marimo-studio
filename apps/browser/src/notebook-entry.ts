import { connectNotebookEntry } from "@marimo-studio/marimo-frontend/notebook-entry";

import css from "./notebook-entry.css?inline";

const disconnect = connectNotebookEntry((target, save) => {
  const style = document.createElement("style");
  style.textContent = css;
  const toolbar = document.createElement("header");
  toolbar.setAttribute("aria-label", "Studio");
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "+ Add view";
  button.title = "Save this notebook to add a view";
  button.addEventListener("click", save);
  toolbar.append(button);
  target.append(style, toolbar);
  return () => button.removeEventListener("click", save);
});
window.addEventListener("pagehide", (event) => {
  if (!event.persisted) disconnect();
});
