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
import { useDisclosureMenu } from "../../shared/useDisclosureMenu.ts";

const BUILD_DISPLAY = {
  unbuilt: { label: "Not built", icon: CircleDashedIcon },
  building: { label: "Building", icon: LoaderCircleIcon },
  checking: { label: "Checking build", icon: LoaderCircleIcon },
  failed: { label: "Build failed", icon: CircleXIcon },
  published: { label: "Up to date", icon: CircleCheckIcon },
  stale: { label: "Build needed", icon: RefreshCwIcon },
  unavailable: { label: "Build status unavailable", icon: CircleHelpIcon },
} as const;

const buildRelationship = (phase: ViewBuildState["phase"], published: boolean): string => {
  if (phase === "stale") {
    return "Saved source has changed. Build the view to update Preview.";
  }
  if (phase === "failed" && published) {
    return "The latest build failed. Preview still shows the last successful version.";
  }
  if (phase === "building" && published) {
    return "Preview stays available while the update builds.";
  }
  if (phase === "published") {
    return "Preview matches the saved source.";
  }
  return published
    ? "Preview shows the last successful build."
    : "Build the view to create its first preview.";
};

export const SourceProjectDetails = ({
  artifact,
  build,
  diagnostic,
  inspection,
}: {
  artifact?: PublishedArtifact | null;
  build: ViewBuildState;
  diagnostic?: ProjectDiagnostic;
  inspection: ProjectInspection;
}) => {
  const menu = useDisclosureMenu();
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
        ref={menu.detailsRef}
        className="studio-menu studio-source-details"
        data-studio-disclosure-menu
        data-phase={phase}
        onKeyDown={menu.onKeyDown}
        onToggle={menu.onToggle}
      >
        <summary
          ref={menu.triggerRef}
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
          aria-label="View build status"
          role="region"
        >
          <strong className="studio-menu-heading">Build status</strong>
          <p className="studio-source-build-relationship">{relationship}</p>
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
