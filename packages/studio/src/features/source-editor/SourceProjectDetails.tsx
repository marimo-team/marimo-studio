import type {
  ProjectDiagnostic,
  PublishedArtifact,
  ViewBuildState,
} from "@marimo-studio/protocol/view-project";

import {
  CircleCheckIcon,
  CircleDashedIcon,
  CircleHelpIcon,
  CircleXIcon,
  LoaderCircleIcon,
  RefreshCwIcon,
} from "lucide-react";

import type { ProjectInspection } from "./session.ts";

import { MenuChevron } from "../../shared/ui/icons.tsx";

const BUILD_DISPLAY = {
  unbuilt: { label: "Not built", icon: CircleDashedIcon },
  building: { label: "Building", icon: LoaderCircleIcon },
  checking: { label: "Checking build", icon: LoaderCircleIcon },
  failed: { label: "Build failed", icon: CircleXIcon },
  published: { label: "Up to date", icon: CircleCheckIcon },
  stale: { label: "Build needed", icon: RefreshCwIcon },
  unavailable: { label: "Build status unavailable", icon: CircleHelpIcon },
} as const;

const revisionLabel = (revision: string | null | undefined): string => {
  if (!revision) {
    return "Pending";
  }
  return revision.replace(/^sha256:/, "").slice(0, 10);
};

const buildRelationship = (phase: ViewBuildState["phase"], published: boolean): string => {
  if (phase === "stale") {
    return "Source is newer than the published view.";
  }
  if (phase === "failed" && published) {
    return "The last successful view remains available.";
  }
  if (phase === "building" && published) {
    return "The current view remains available while the update builds.";
  }
  if (phase === "published") {
    return "Source and published view match.";
  }
  return published ? "A published view is available." : "No view has been published yet.";
};

export const SourceProjectDetails = ({
  artifact,
  build,
  diagnostic,
  inspection,
  provider,
}: {
  artifact?: PublishedArtifact | null;
  build: ViewBuildState;
  diagnostic?: ProjectDiagnostic;
  inspection: ProjectInspection;
  provider?: string;
}) => {
  const phase = inspection.phase === "ready" ? build.phase : inspection.phase;
  const { icon: BuildIcon, label } = BUILD_DISPLAY[phase];
  let relationship: string;
  if (inspection.phase === "ready") {
    relationship = buildRelationship(build.phase, artifact !== null && artifact !== undefined);
  } else if (inspection.phase === "checking") {
    relationship = "Checking current source against the published view.";
  } else {
    relationship = inspection.message;
  }
  return (
    <>
      <details
        className="studio-menu studio-source-details"
        data-phase={phase}
        onKeyDown={(event) => {
          if (event.key !== "Escape" || !event.currentTarget.open) {
            return;
          }
          event.preventDefault();
          const details = event.currentTarget;
          const trigger = details.querySelector("summary");
          details.removeAttribute("open");
          globalThis.requestAnimationFrame(() => trigger?.focus());
        }}
      >
        <summary
          className="studio-control studio-menu-trigger studio-source-details-trigger"
          aria-label={`View build details, ${label}`}
          tabIndex={0}
        >
          <BuildIcon className="studio-source-build-icon" aria-hidden="true" focusable="false" />
          <span>{label}</span>
          <MenuChevron />
        </summary>
        <div
          className="studio-menu-popover studio-source-details-popover"
          aria-label="View project details"
        >
          <strong className="studio-menu-heading">View details</strong>
          <p className="studio-source-build-relationship">{relationship}</p>
          <dl className="studio-source-details-list">
            <div>
              <dt>Provider</dt>
              <dd>
                <code>{provider ?? "Pending"}</code>
              </dd>
            </div>
            <div>
              <dt>{inspection.phase === "ready" ? "Project revision" : "Last checked revision"}</dt>
              <dd>
                <code title={build.project_revision ?? "Project revision pending"}>
                  {revisionLabel(build.project_revision)}
                </code>
              </dd>
            </div>
            <div>
              <dt>Published revision</dt>
              <dd>
                <code title={artifact?.artifact_id ?? "No published view"}>
                  {artifact ? revisionLabel(artifact.artifact_id) : "None"}
                </code>
              </dd>
            </div>
          </dl>
          {diagnostic ? (
            <p className="studio-source-project-diagnostic" data-severity={diagnostic.severity}>
              <span>{diagnostic.message}</span>
              {diagnostic.hint ? <small>{diagnostic.hint}</small> : null}
            </p>
          ) : null}
        </div>
      </details>
      <span className="studio-visually-hidden" role="status" aria-label="View build status">
        {label}
      </span>
    </>
  );
};
