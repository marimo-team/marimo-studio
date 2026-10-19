import type { Starter } from "@marimo-studio/protocol/provider-catalog";

import { SearchIcon } from "lucide-react";
import { type ReactNode, useId, useState } from "react";

import { StarterMark } from "./StarterPreview.tsx";
import {
  groupStartersByDistribution,
  homepageHost,
  matchesStarterQuery,
  setupLabel,
} from "./starters.ts";

const StarterOption = ({
  starter,
  selected,
  previewUrl,
  onSelect,
}: {
  starter: Starter;
  selected: boolean;
  previewUrl: string | undefined;
  onSelect: (starter: string) => void;
}) => (
  <label className="studio-starter-option" data-selected={selected || undefined}>
    <input
      type="radio"
      name="starter"
      className="studio-visually-hidden"
      value={starter.id}
      checked={selected}
      onChange={() => onSelect(starter.id)}
      onFocus={(event) =>
        event.currentTarget.closest("label")?.scrollIntoView({ block: "nearest" })
      }
    />
    <StarterMark starter={starter} url={previewUrl} />
    <span className="studio-starter-option-text">
      <strong>{starter.title}</strong>
      {starter.availability.available ? (
        <small>
          {starter.format ?? (starter.homepage ? homepageHost(starter.homepage) : starter.provider)}
        </small>
      ) : (
        <small className="studio-starter-option-setup">{setupLabel(starter)}</small>
      )}
    </span>
  </label>
);

export const StarterList = ({
  starters,
  selected,
  previewUrl,
  notice,
  onSelect,
}: {
  starters: readonly Starter[];
  selected: string;
  previewUrl: (starter: Starter) => string | undefined;
  /** Catalog loading or recovery state, shown above the starters. */
  notice: ReactNode;
  onSelect: (starter: string) => void;
}) => {
  const searchId = useId();
  const [query, setQuery] = useState("");

  const groups = groupStartersByDistribution(
    starters.filter((starter) => matchesStarterQuery(starter, query)),
  );
  return (
    <div className="studio-starter-browser">
      <label className="studio-starter-search" htmlFor={searchId}>
        <SearchIcon aria-hidden="true" />
        <input
          id={searchId}
          type="search"
          placeholder="Search starters"
          aria-label="Search starters"
          autoComplete="off"
          spellCheck={false}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>
      <fieldset className="studio-starter-groups">
        <legend className="studio-visually-hidden">Starter</legend>
        {notice}
        {groups.map((group) => (
          <fieldset key={group.distribution} className="studio-starter-group">
            <legend>
              <code>{group.distribution}</code>
            </legend>
            {group.starters.map((starter) => (
              <StarterOption
                key={starter.id}
                starter={starter}
                selected={starter.id === selected}
                previewUrl={previewUrl(starter)}
                onSelect={onSelect}
              />
            ))}
          </fieldset>
        ))}
        {groups.length === 0 && query.trim() ? (
          <p className="studio-starter-empty" role="status">
            No starter matches “{query.trim()}”.
          </p>
        ) : null}
      </fieldset>
    </div>
  );
};
