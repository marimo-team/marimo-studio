import type { SettingValue, Starter } from "@marimo-studio/protocol/provider-catalog";
import type { CreateViewRequest } from "@marimo-studio/protocol/views";

import { useCallback, useMemo, useState } from "react";

import { preferredStarterId } from "./starters.ts";

/** Everything a person chooses in the New view dialog before Studio creates the view. */
export interface ViewDraft {
  name: string;
  starter: string;
  /** The display title, or an empty string to derive it from the name. */
  title: string;
  makeDefault: boolean;
  /** Setting values a person changed, kept per starter so switching back restores them. */
  settings: Readonly<Record<string, Readonly<Record<string, SettingValue>>>>;
}

export interface ViewDraftModel {
  value: ViewDraft;
  selected: Starter | undefined;
  update: (patch: Partial<Omit<ViewDraft, "settings">>) => void;
  setSetting: (key: string, value: SettingValue) => void;
  reset: () => void;
  request: (catalogGeneration: string) => CreateViewRequest;
}

/** Return the title Studio derives from a view name, matching Python's `str.title()`. */
export const viewTitle = (name: string): string =>
  name
    .replaceAll("-", " ")
    .replace(/[a-z]+/gi, (word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase());

export const settingValue = (
  draft: ViewDraft,
  starter: Starter,
  setting: Starter["settings"][number],
): SettingValue => draft.settings[starter.id]?.[setting.key] ?? setting.default;

export const useViewDraft = ({
  starters,
  defaultStarter,
  initialName = "",
}: {
  starters: readonly Starter[];
  defaultStarter: string;
  initialName?: string;
}): ViewDraftModel => {
  const initial = useMemo<ViewDraft>(
    () => ({ name: initialName, starter: "", title: "", makeDefault: false, settings: {} }),
    [initialName],
  );
  const [chosen, setValue] = useState<ViewDraft>(initial);
  // Until a person picks a starter that the catalog lists, the draft follows
  // the catalog's preferred starter, which can change as the catalog loads.
  const value = useMemo<ViewDraft>(
    () =>
      starters.some((candidate) => candidate.id === chosen.starter)
        ? chosen
        : { ...chosen, starter: preferredStarterId(starters, defaultStarter) },
    [chosen, defaultStarter, starters],
  );

  const update = useCallback(
    (patch: Partial<Omit<ViewDraft, "settings">>) =>
      setValue((current) => ({ ...current, ...patch })),
    [],
  );
  const setSetting = useCallback(
    (key: string, setting: SettingValue) =>
      setValue((current) => ({
        ...current,
        starter: value.starter,
        settings: {
          ...current.settings,
          [value.starter]: { ...current.settings[value.starter], [key]: setting },
        },
      })),
    [value.starter],
  );
  const reset = useCallback(
    () => setValue({ ...initial, starter: value.starter }),
    [initial, value.starter],
  );
  const request = useCallback(
    (catalogGeneration: string): CreateViewRequest => ({
      catalog_generation: catalogGeneration,
      name: value.name,
      starter: value.starter,
      title: value.title.trim() || null,
      settings: { ...value.settings[value.starter] },
      make_default: value.makeDefault,
    }),
    [value],
  );
  return {
    value,
    selected: starters.find((candidate) => candidate.id === value.starter),
    update,
    setSetting,
    reset,
    request,
  };
};
