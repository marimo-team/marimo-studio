import type { Starter } from "@marimo-studio/protocol/provider-catalog";

export const StarterPlan = ({ starter }: { starter: Starter }) => (
  <>
    <small className="studio-starter-documents">Starts with {starter.documents.join(", ")}</small>
    {!starter.availability.available ? (
      <small className="studio-starter-action">
        {starter.availability.action ?? starter.availability.reason}
      </small>
    ) : null}
  </>
);
