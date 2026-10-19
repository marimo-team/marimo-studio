import type { SettingValue, Starter } from "@marimo-studio/protocol/provider-catalog";

import { useId } from "react";

import type { ViewDraftModel } from "./useViewDraft.ts";

import { HelpTip } from "../../shared/ui/HelpTip.tsx";
import { settingValue, viewTitle } from "./useViewDraft.ts";

const SEGMENTED_CHOICES = 3;

/** One row in the settings panel, whether Studio or the starter declares it. */
interface SettingField {
  key: string;
  label: string;
  help: string;
  kind: "boolean" | "choice" | "text";
  value: SettingValue;
  choices: readonly { value: string; label: string }[];
  placeholder?: string;
  maxLength?: number;
  disabled?: boolean;
  onChange: (value: SettingValue) => void;
}

const studioFields = (draft: ViewDraftModel, firstView: boolean): SettingField[] => [
  {
    key: "studio:title",
    label: "Title",
    help: "The title the starter writes into the view. Leave it empty to use a title made from the view name.",
    kind: "text",
    value: draft.value.title,
    choices: [],
    placeholder: viewTitle(draft.value.name) || "Made from the view name",
    maxLength: 200,
    onChange: (title) => draft.update({ title: String(title) }),
  },
  {
    key: "studio:make_default",
    label: "Default view",
    help: firstView
      ? "The notebook's first view always becomes its default view."
      : "Serve this view at the notebook's main route and open it first in Studio.",
    kind: "boolean",
    value: firstView || draft.value.makeDefault,
    choices: [],
    disabled: firstView,
    onChange: (makeDefault) => draft.update({ makeDefault: makeDefault === true }),
  },
];

const starterFields = (draft: ViewDraftModel, starter: Starter): SettingField[] =>
  starter.settings.map((setting) => ({
    key: `${starter.id}:${setting.key}`,
    label: setting.label,
    help: setting.help,
    kind: setting.kind,
    value: settingValue(draft.value, starter, setting),
    choices: setting.choices,
    maxLength: 4096,
    onChange: (value) => draft.setSetting(setting.key, value),
  }));

const isSegmented = (field: SettingField): boolean =>
  field.kind === "choice" && field.choices.length <= SEGMENTED_CHOICES;

const SettingControl = ({
  field,
  id,
  describedBy,
  disabled,
}: {
  field: SettingField;
  id: string;
  describedBy: string;
  disabled: boolean;
}) => {
  if (field.kind === "boolean") {
    return (
      <button
        id={id}
        type="button"
        role="switch"
        className="studio-switch"
        aria-checked={field.value === true}
        aria-describedby={describedBy}
        disabled={disabled}
        onClick={() => field.onChange(field.value !== true)}
      >
        <span aria-hidden="true" />
      </button>
    );
  }
  if (isSegmented(field)) {
    return (
      <div
        id={id}
        role="radiogroup"
        className="studio-segmented"
        aria-labelledby={`${id}-label`}
        aria-describedby={describedBy}
      >
        {field.choices.map((choice) => (
          <label key={choice.value} data-selected={choice.value === field.value || undefined}>
            <input
              type="radio"
              className="studio-visually-hidden"
              name={id}
              value={choice.value}
              checked={choice.value === field.value}
              disabled={disabled}
              onChange={() => field.onChange(choice.value)}
            />
            {choice.label}
          </label>
        ))}
      </div>
    );
  }
  if (field.kind === "choice") {
    return (
      <select
        id={id}
        className="studio-setting-select"
        aria-labelledby={`${id}-label`}
        aria-describedby={describedBy}
        value={String(field.value)}
        disabled={disabled}
        onChange={(event) => field.onChange(event.target.value)}
      >
        {field.choices.map((choice) => (
          <option key={choice.value} value={choice.value}>
            {choice.label}
          </option>
        ))}
      </select>
    );
  }
  return (
    <input
      id={id}
      type="text"
      className="studio-setting-text"
      maxLength={field.maxLength}
      aria-describedby={describedBy}
      autoComplete="off"
      placeholder={field.placeholder}
      value={String(field.value)}
      disabled={disabled}
      onChange={(event) => field.onChange(event.target.value)}
    />
  );
};

const SettingRow = ({ field, busy }: { field: SettingField; busy: boolean }) => {
  const id = useId();
  const helpId = `${id}-help`;
  return (
    <div className="studio-setting" data-kind={field.kind}>
      <div className="studio-setting-label">
        <label id={`${id}-label`} htmlFor={isSegmented(field) ? undefined : id}>
          {field.label}
        </label>
        <HelpTip id={helpId} label={field.label} text={field.help} />
      </div>
      <SettingControl
        field={field}
        id={id}
        describedBy={helpId}
        disabled={busy || field.disabled === true}
      />
    </div>
  );
};

export const ViewSettings = ({
  draft,
  starter,
  firstView,
  busy,
}: {
  draft: ViewDraftModel;
  starter: Starter;
  firstView: boolean;
  busy: boolean;
}) => {
  const fields = [...studioFields(draft, firstView), ...starterFields(draft, starter)];
  return (
    <section className="studio-view-settings" aria-labelledby="studio-view-settings-title">
      <h4 id="studio-view-settings-title">Settings</h4>
      <div className="studio-setting-list">
        {fields.map((field) => (
          <SettingRow key={field.key} field={field} busy={busy} />
        ))}
      </div>
    </section>
  );
};
