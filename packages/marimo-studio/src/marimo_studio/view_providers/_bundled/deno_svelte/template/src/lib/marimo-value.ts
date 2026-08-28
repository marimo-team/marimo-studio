type MarimoValueElement<T> = HTMLElement & {
  marimoValue?: T;
};

type MarimoValueOptions<T> = {
  selector: string;
  onValue: (value: T) => void;
  onError?: () => void;
};

/** Subscribe an explicit `mo-value` host to current values and later updates. */
export const observeMarimoValue = <T>(
  node: HTMLElement,
  options: MarimoValueOptions<T>,
) => {
  let current = options;
  const host = node as MarimoValueElement<T>;

  const sync = () => {
    if (host.marimoValue !== undefined) {
      current.onValue(host.marimoValue);
    }
  };
  const fail = () => current.onError?.();

  host.addEventListener("marimo-value-updated", sync);
  host.addEventListener("marimo-value-error", fail);
  sync();

  return {
    update(next: MarimoValueOptions<T>) {
      current = next;
    },
    destroy() {
      host.removeEventListener("marimo-value-updated", sync);
      host.removeEventListener("marimo-value-error", fail);
    },
  };
};
