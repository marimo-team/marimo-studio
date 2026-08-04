import type { CellBindingConfig, ValueBindingConfig } from "../../runtime-config/index";

import { cellBindingKey } from "../../cells/bindings";

export interface ValueGroup {
  binding: CellBindingConfig;
  key: string;
  selectors: string[];
}

export const groupValueBindings = (
  bindings: Readonly<Record<string, ValueBindingConfig>>,
): ValueGroup[] => {
  const groups = new Map<string, { binding: CellBindingConfig; selectors: Set<string> }>();
  Object.entries(bindings).forEach(([selector, binding]) => {
    const key = cellBindingKey(binding.cell);
    const group = groups.get(key) ?? {
      binding: binding.cell,
      selectors: new Set<string>(),
    };
    group.selectors.add(selector);
    groups.set(key, group);
  });
  return Array.from(groups, ([key, group]) => ({
    key,
    binding: group.binding,
    selectors: Array.from(group.selectors).sort(),
  }));
};
