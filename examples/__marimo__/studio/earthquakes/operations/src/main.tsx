// @deno-types="npm:@types/react-dom@19.2.3/client.d.ts"
import { createRoot } from "react-dom/client";
import { setWorkerUrl } from "maplibre-gl";

import { App } from "./App.tsx";
import "./style.css";

const root = document.getElementById("app-shell");

if (root === null) {
  throw new Error("React view requires #app-shell");
}

// Dynamic import lets Deno emit the worker entry and its dependency graph.
const { workerUrl } = await import("./map-worker.ts");
setWorkerUrl(workerUrl);

createRoot(root).render(<App />);
