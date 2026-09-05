// @deno-types="npm:@types/react-dom@19.2.3/client.d.ts"
import { createRoot } from "react-dom/client";

import { App } from "./App.tsx";
import "./style.css";

const root = document.getElementById("app-shell");

if (root === null) {
  throw new Error("React view requires #app-shell");
}

createRoot(root).render(<App />);
