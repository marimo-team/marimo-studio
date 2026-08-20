import {
  jsonValueSchema,
  type NativeRuntimeControls,
  type RuntimeControlBinding,
  type RuntimeControls,
} from "@marimo-studio/protocol/runtime-config";

import type {
  ControlUpdate,
  EndpointControlBinding,
  EndpointControlBindings,
} from "./control-types.ts";

interface NativeCellIdentity {
  readonly semantic: string;
  readonly runtime: string;
}

export interface ControlTranslation {
  editor(update: ControlUpdate): readonly ControlUpdate[];
  editorFromBinding(
    binding: EndpointControlBinding,
    update: ControlUpdate,
  ): readonly ControlUpdate[];
  editorHasSource(objectId: string): boolean;
  preview(update: ControlUpdate): readonly ControlUpdate[];
  previewFromBinding(
    binding: EndpointControlBinding,
    update: ControlUpdate,
  ): readonly ControlUpdate[];
  previewHasSource(objectId: string): boolean;
}

const bindingKey = (binding: EndpointControlBinding): string =>
  JSON.stringify([
    binding.input,
    binding.path.map((step) => (step.kind === "element" ? [step.kind] : [step.kind, step.value])),
  ]);

export const sameControlBindings = (
  left: EndpointControlBindings,
  right: EndpointControlBindings,
): boolean => {
  const leftEntries = Object.entries(left);
  return (
    leftEntries.length === Object.keys(right).length &&
    leftEntries.every(([objectId, binding]) => {
      const candidate = Object.hasOwn(right, objectId) ? right[objectId] : undefined;
      return candidate !== undefined && bindingKey(candidate) === bindingKey(binding);
    })
  );
};

export const sameRuntimeControls = (
  left: RuntimeControls | undefined,
  right: RuntimeControls | undefined,
): boolean => {
  if (!left || !right) {
    return left === right;
  }
  const bindingsEqual =
    left.bindings === undefined || right.bindings === undefined
      ? left.bindings === right.bindings
      : sameControlBindings(left.bindings, right.bindings);
  const nativeEqual =
    left.native === undefined || right.native === undefined
      ? left.native === right.native
      : JSON.stringify(
          Object.entries(left.native.cells).sort(([leftKey], [rightKey]) =>
            leftKey.localeCompare(rightKey),
          ),
        ) ===
        JSON.stringify(
          Object.entries(right.native.cells).sort(([leftKey], [rightKey]) =>
            leftKey.localeCompare(rightKey),
          ),
        );
  return bindingsEqual && nativeEqual;
};

const targetsByBinding = (
  bindings: Readonly<Record<string, RuntimeControlBinding>>,
): ReadonlyMap<string, readonly string[]> => {
  const targets = new Map<string, string[]>();
  for (const [objectId, binding] of Object.entries(bindings)) {
    const key = bindingKey(binding);
    const ids = targets.get(key) ?? [];
    ids.push(objectId);
    targets.set(key, ids);
  }
  return targets;
};

export const controlBindingsConverged = (
  left: RuntimeControls,
  right: RuntimeControls,
): boolean => {
  if (left.bindings !== undefined && right.bindings !== undefined) {
    const leftKeys = new Set(Object.values(left.bindings).map(bindingKey));
    const rightKeys = new Set(Object.values(right.bindings).map(bindingKey));
    return Array.from(rightKeys).every((key) => leftKeys.has(key));
  }
  return left.native !== undefined && right.native !== undefined;
};

export const controlContractsCompatible = (
  left: RuntimeControls,
  right: RuntimeControls,
): boolean =>
  (left.bindings !== undefined && right.bindings !== undefined) ||
  (left.native !== undefined && right.native !== undefined);

const translateBinding = (
  update: ControlUpdate,
  source: Readonly<Record<string, RuntimeControlBinding>>,
  target: ReadonlyMap<string, readonly string[]>,
): readonly ControlUpdate[] => {
  const binding = Object.hasOwn(source, update.objectId) ? source[update.objectId] : undefined;
  if (!binding) {
    return [];
  }
  return translateCapturedBinding(binding, update, target);
};

const translateCapturedBinding = (
  binding: EndpointControlBinding,
  update: ControlUpdate,
  target: ReadonlyMap<string, readonly string[]>,
): readonly ControlUpdate[] => {
  const value = jsonValueSchema.safeParse(update.value);
  if (!value.success) {
    return [];
  }
  return (target.get(bindingKey(binding)) ?? []).map((objectId) => ({
    objectId,
    value: value.data,
  }));
};

const nativeCellsByRuntimeId = (controls: NativeRuntimeControls): readonly NativeCellIdentity[] =>
  Object.entries(controls.cells)
    .map(([semantic, runtime]) => ({ semantic, runtime }))
    .sort((left, right) => right.runtime.length - left.runtime.length);

const translateNative = (
  update: ControlUpdate,
  source: readonly NativeCellIdentity[],
  target: NativeRuntimeControls,
): readonly ControlUpdate[] => {
  const cell = source.find(({ runtime }) => update.objectId.startsWith(`${runtime}-`));
  const value = jsonValueSchema.safeParse(update.value);
  if (!cell || !value.success) {
    return [];
  }
  const targetCell = Object.hasOwn(target.cells, cell.semantic)
    ? target.cells[cell.semantic]
    : undefined;
  if (!targetCell) {
    return [];
  }
  return [
    {
      objectId: `${targetCell}${update.objectId.slice(cell.runtime.length)}`,
      value: value.data,
    },
  ];
};

export const createControlTranslation = (
  editor: RuntimeControls,
  preview: RuntimeControls,
): ControlTranslation => {
  const editorBindings = editor.bindings;
  const previewBindings = preview.bindings;
  if (editorBindings !== undefined && previewBindings !== undefined) {
    const editorTargets = targetsByBinding(editorBindings);
    const previewTargets = targetsByBinding(previewBindings);
    return {
      editor: (update) => translateBinding(update, editorBindings, previewTargets),
      editorFromBinding: (binding, update) =>
        translateCapturedBinding(binding, update, previewTargets),
      editorHasSource: (objectId) => Object.hasOwn(editorBindings, objectId),
      preview: (update) => translateBinding(update, previewBindings, editorTargets),
      previewFromBinding: (binding, update) =>
        translateCapturedBinding(binding, update, editorTargets),
      previewHasSource: (objectId) => Object.hasOwn(previewBindings, objectId),
    };
  }
  const editorNative = editor.native;
  const previewNative = preview.native;
  if (editorNative !== undefined && previewNative !== undefined) {
    const editorCells = nativeCellsByRuntimeId(editorNative);
    const previewCells = nativeCellsByRuntimeId(previewNative);
    return {
      editor: (update) => translateNative(update, editorCells, previewNative),
      editorFromBinding: () => [],
      editorHasSource: (objectId) =>
        editorCells.some(({ runtime }) => objectId.startsWith(`${runtime}-`)),
      preview: (update) => translateNative(update, previewCells, editorNative),
      previewFromBinding: () => [],
      previewHasSource: (objectId) =>
        previewCells.some(({ runtime }) => objectId.startsWith(`${runtime}-`)),
    };
  }
  throw new Error("Control endpoints do not share a synchronization contract");
};
