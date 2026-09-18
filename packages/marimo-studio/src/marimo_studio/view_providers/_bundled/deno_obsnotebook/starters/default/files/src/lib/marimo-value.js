import { library } from "@observablehq/notebook-kit/runtime";

/** Turn an explicit mo-value host into an Observable reactive value. */
export function marimoValue(host) {
  return library.Generators().observe((notify) => {
    const dispose = () => {
      host.removeEventListener("marimo-value-updated", sync);
      host.removeEventListener("marimo-value-error", fail);
    };
    const fail = (event) => {
      const error = Promise.reject(
        new Error(
          event?.detail?.message || host.dataset.marimoDiagnosticMessage ||
            "Projected value unavailable",
        ),
      );
      // Observable pulls on its next frame; handle the rejection until then.
      error.catch(() => {});
      notify(error);
      dispose();
    };
    const sync = () => {
      if (host.dataset.state === "error") fail();
      else if (host.marimoValue !== undefined) notify(host.marimoValue);
    };
    host.addEventListener("marimo-value-updated", sync);
    host.addEventListener("marimo-value-error", fail);
    sync();
    return dispose;
  });
}
