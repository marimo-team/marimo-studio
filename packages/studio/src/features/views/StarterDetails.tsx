import type { Starter } from "@marimo-studio/protocol/provider-catalog";
import type { HostPersistence } from "@marimo-studio/protocol/views";

import { ArrowUpRightIcon, TriangleAlertIcon } from "lucide-react";
import { Fragment, type ReactNode } from "react";

import { StarterMark, StarterPreview } from "./StarterPreview.tsx";
import { homepageHost, setupLabel } from "./starters.ts";

const CREATES_SHOWN = 3;
const INLINE_MARKUP = /(`[^`]+`|https:\/\/[^\s`]+[^\s`.,;:!?)])/g;

const PERSISTENCE_NOTICES = {
  source:
    "View files are lost when this session ends because marimohub saves only notebook.py and pyproject.toml. A hub administrator can set MARIMOHUB_PERSIST_WORKSPACE=workspace to keep them.",
  none: "View files are lost when this session ends because marimohub saves no files from it. For a Git-synced notebook, commit notebook.py and the view folder before you stop the session.",
} as const;

/** Render provider guidance with its `commands` as code and its https URLs as links. */
const GuidanceText = ({ text }: { text: string }) => (
  <>
    {text.split(INLINE_MARKUP).map((part, index) => {
      if (index % 2 === 0) {
        return <Fragment key={index}>{part}</Fragment>;
      }
      if (part.startsWith("`")) {
        return <code key={index}>{part.slice(1, -1)}</code>;
      }
      return (
        <a key={index} href={part} target="_blank" rel="noreferrer">
          {part.replace(/^https:\/\//, "")}
        </a>
      );
    })}
  </>
);

const Fact = ({ label, children }: { label: string; children: ReactNode }) => (
  <div className="studio-starter-fact">
    <dt>{label}</dt>
    <dd>{children}</dd>
  </div>
);

export const persistenceNotice = (persistence: HostPersistence): string | undefined =>
  persistence === "source" || persistence === "none" ? PERSISTENCE_NOTICES[persistence] : undefined;

export const StarterDetails = ({
  starter,
  previewUrl,
  folder,
  persistence,
}: {
  starter: Starter;
  previewUrl: string | undefined;
  folder: string;
  persistence: HostPersistence;
}) => {
  const { availability } = starter;
  const created = starter.documents.slice(0, CREATES_SHOWN);
  const more = starter.documents.length - created.length;
  const notice = persistenceNotice(persistence);
  return (
    <section className="studio-starter-details" aria-labelledby="studio-starter-title">
      <StarterPreview starter={starter} url={previewUrl} folder={folder} />
      <header className="studio-starter-heading">
        <div className="studio-starter-title">
          <StarterMark starter={starter} url={previewUrl} />
          <h3 id="studio-starter-title">{starter.title}</h3>
          {starter.format ? <span className="studio-starter-format">{starter.format}</span> : null}
        </div>
        <p>{starter.summary}</p>
      </header>
      <dl className="studio-starter-facts">
        <Fact label="Provider">
          <code>{starter.provider}</code>
          {availability.version ? (
            <span className="studio-starter-version">{availability.version}</span>
          ) : null}
        </Fact>
        {starter.homepage ? (
          <Fact label="Website">
            <a href={starter.homepage} target="_blank" rel="noreferrer">
              <span>{homepageHost(starter.homepage)}</span>
              <ArrowUpRightIcon aria-hidden="true" />
            </a>
          </Fact>
        ) : null}
        <Fact label="Creates">
          <span className="studio-starter-documents" title={starter.documents.join("\n")}>
            {created.map((document) => (
              <code key={document}>{document}</code>
            ))}
            {more > 0 ? <span>+{more} more</span> : null}
          </span>
        </Fact>
      </dl>
      {!availability.available ? (
        <div className="studio-starter-setup" role="note">
          <strong>
            <TriangleAlertIcon aria-hidden="true" />
            {setupLabel(starter)}
          </strong>
          {availability.reason ? (
            <p>
              <GuidanceText text={availability.reason} />
            </p>
          ) : null}
          {availability.action ? (
            <p>
              <GuidanceText text={availability.action} />
            </p>
          ) : null}
        </div>
      ) : null}
      {notice ? (
        <p id="studio-view-persistence" className="studio-starter-persistence" role="note">
          {notice}
        </p>
      ) : null}
    </section>
  );
};
