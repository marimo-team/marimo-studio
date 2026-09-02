/// <reference path="./marimo-studio.d.ts" />

import { Deck } from "@revealjs/react";
import "reveal.js/reveal.css";
import { useMemo } from "react";
import {
  createBriefingModel,
  type DailyActivity,
  type EventSummary,
  type StrongEvent,
  type WeeklySummary,
} from "./briefing-data.ts";
import {
  CoverSlide,
  ExecutiveSlide,
  HandoffSlide,
  OperatingPictureSlide,
  TempoSlide,
  WatchlistSlide,
} from "./components/BriefingSlides.tsx";
import { type MarimoTable, useMarimoValue } from "./lib/use-marimo-value.ts";

const deckConfig = {
  autoAnimateDuration: 0.85,
  autoAnimateEasing: "cubic-bezier(0.77, 0, 0.175, 1)",
  center: false,
  controls: true,
  controlsTutorial: false,
  hash: false,
  height: "100%",
  margin: 0.025,
  progress: true,
  scrollActivationWidth: 0,
  showSlideNumber: "all",
  slideNumber: "c/t",
  transition: "fade",
  transitionSpeed: "fast",
  width: "100%",
} as const;

export const App = () => {
  const summaryProjection = useMarimoValue<EventSummary>("event_summary");
  const weeklyProjection = useMarimoValue<WeeklySummary>("weekly_summary");
  const activityProjection = useMarimoValue<MarimoTable<DailyActivity>>(
    "daily_activity",
  );
  const eventsProjection = useMarimoValue<MarimoTable<StrongEvent>>(
    "strongest_events",
  );

  const activity = useMemo(
    () => activityProjection.value?.toArray() ?? [],
    [activityProjection.value],
  );
  const strongest = useMemo(
    () => eventsProjection.value?.toArray().slice(0, 5) ?? [],
    [eventsProjection.value],
  );
  const model = useMemo(
    () =>
      createBriefingModel({
        activity,
        strongest,
        summary: summaryProjection.value,
        weekly: weeklyProjection.value,
      }),
    [activity, strongest, summaryProjection.value, weeklyProjection.value],
  );
  const projectionError = summaryProjection.error ||
    weeklyProjection.error ||
    activityProjection.error ||
    eventsProjection.error;
  const loading = !projectionError &&
    (summaryProjection.value === undefined ||
      weeklyProjection.value === undefined ||
      activityProjection.value === undefined ||
      eventsProjection.value === undefined);

  return (
    <>
      <span
        aria-hidden="true"
        className="value-host"
        hidden
        mo-value="event_summary"
        ref={summaryProjection.hostRef}
      />
      <span
        aria-hidden="true"
        className="value-host"
        hidden
        mo-value="weekly_summary"
        ref={weeklyProjection.hostRef}
      />
      <span
        aria-hidden="true"
        className="value-host"
        hidden
        mo-value="daily_activity"
        ref={activityProjection.hostRef}
      />
      <span
        aria-hidden="true"
        className="value-host"
        hidden
        mo-value="strongest_events"
        ref={eventsProjection.hostRef}
      />

      <main className="deck-shell">
        {loading
          ? (
            <div className="briefing-loader" role="status">
              <span className="briefing-loader-sheet" aria-hidden="true">
                <i />
                <i />
                <i />
                <i />
              </span>
              Preparing weekly briefing
            </div>
          )
          : null}
        {projectionError
          ? (
            <p className="deck-error" role="alert">
              Briefing data could not be loaded. Reload the page to retry.
            </p>
          )
          : null}

        <Deck className="studio-deck" config={deckConfig}>
          <CoverSlide model={model} />
          <ExecutiveSlide model={model} />
          <TempoSlide model={model} />
          <OperatingPictureSlide model={model} />
          <WatchlistSlide model={model} />
          <HandoffSlide model={model} />
        </Deck>
      </main>
    </>
  );
};
