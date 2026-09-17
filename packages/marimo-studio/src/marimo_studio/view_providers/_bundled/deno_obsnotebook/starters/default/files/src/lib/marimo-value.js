import { library } from "@observablehq/notebook-kit/runtime";

/** Turn an explicit mo-value host into an Observable reactive value. */
export function marimoValue(host) {
  return library.Generators().observe((notify) => {
    const sync = () => {
      if (host.marimoValue !== undefined) notify(host.marimoValue);
    };
    host.addEventListener("marimo-value-updated", sync);
    sync();
    return () => host.removeEventListener("marimo-value-updated", sync);
  });
}
