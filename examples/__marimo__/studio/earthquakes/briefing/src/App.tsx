/// <reference path="./marimo-studio.d.ts" />

import { Deck } from "@revealjs/react";
import "reveal.js/reveal.css";
// @deno-types="npm:@types/react@19.2.10"
import { useMemo, useSyncExternalStore } from "react";
import { createBriefingModel, type SeismicAnalysis } from "./briefing-data.ts";
import {
  CatalogSlide,
  CoverSlide,
  FrequencySlide,
  ImpactSlide,
  MagnitudeSlide,
  SelectionSlide,
  TempoSlide,
} from "./components/BriefingSlides.tsx";
import { useMarimoValue } from "./lib/use-marimo-value.ts";

const deckConfig = {
  autoAnimateDuration: 0.8,
  autoAnimateEasing: "cubic-bezier(0.22, 1, 0.36, 1)",
  center: false,
  controls: true,
  controlsTutorial: false,
  hash: false,
  height: 810,
  margin: 0.02,
  progress: true,
  scrollActivationWidth: 0,
  showSlideNumber: "all",
  slideNumber: "c/t",
  transition: "fade",
  transitionSpeed: "fast",
  width: 1440,
} as const;

const portraitReaderQuery = "(max-width: 56rem) and (orientation: portrait)";
const subscribeToPortraitReader = (onChange: () => void) => {
  const media = globalThis.matchMedia(portraitReaderQuery);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
};
const portraitReaderSnapshot = () =>
  globalThis.matchMedia(portraitReaderQuery).matches;
const serverPortraitReaderSnapshot = () => false;

const LessonSlides = (
  { model }: { model: ReturnType<typeof createBriefingModel> },
) => (
  <>
    <CoverSlide model={model} />
    <MagnitudeSlide model={model} />
    <SelectionSlide model={model} />
    <CatalogSlide model={model} />
    <TempoSlide model={model} />
    <FrequencySlide model={model} />
    <ImpactSlide model={model} />
  </>
);

export const App = () => {
  const analysisProjection = useMarimoValue<SeismicAnalysis>(
    "seismic_analysis",
  );
  const model = useMemo(
    () => createBriefingModel(analysisProjection.value),
    [analysisProjection.value],
  );
  const loading = analysisProjection.value === undefined &&
    !analysisProjection.error;
  const usePortraitReader = useSyncExternalStore(
    subscribeToPortraitReader,
    portraitReaderSnapshot,
    serverPortraitReaderSnapshot,
  );

  return (
    <>
      <span
        aria-hidden="true"
        className="value-host"
        hidden
        id="analysis-data"
        mo-value="seismic_analysis"
        ref={analysisProjection.hostRef}
      />

      <span id="briefing-events" hidden mo-value="seismic_analysis.events" />
      <span id="activity-data" hidden mo-value="seismic_analysis.activity" />
      <main
        data-marimo-lens-inputs="analysis-data"
        className="deck-shell"
        aria-busy={loading}
      >
        {loading
          ? (
            <div className="briefing-loader" role="status">
              <span className="loader-seismogram" aria-hidden="true" />
              Preparing the seismic lesson
            </div>
          )
          : null}
        {analysisProjection.error
          ? (
            <p className="deck-error" role="alert">
              The seismic analysis could not be loaded. Reload the page to
              retry.
            </p>
          )
          : null}

        {model.analysis && usePortraitReader
          ? (
            <div className="briefing-reader">
              <header className="reader-header">
                <strong>Earthquake watch</strong>
                <span>7-part lesson · Scroll to read</span>
              </header>
              <LessonSlides model={model} />
            </div>
          )
          : model.analysis
          ? (
            <Deck className="studio-deck" config={deckConfig}>
              <LessonSlides model={model} />
            </Deck>
          )
          : null}
      </main>
    </>
  );
};
