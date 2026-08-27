import { mount } from "svelte";

import App from "./App.svelte";
import "./app.css";

const target = document.querySelector("#app");

if (target === null) {
  throw new Error("The story mount element is missing");
}

mount(App, { target });
