// @deno-types="npm:@types/react@19.2.10"
import React, { StrictMode } from "react";
// @deno-types="npm:@types/react-dom@19.2.3/client.d.ts"
import { createRoot } from "react-dom/client";

import { App } from "./App.tsx";
import "./app.css";

const root = document.querySelector("#app");

if (root === null) {
  throw new Error("The gallery mount element is missing");
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
