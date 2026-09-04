import { Slide } from "@revealjs/react";
import { useState } from "react";
import {
  type BriefingModel,
  feltLabel,
  formatDay,
  formatPeriod,
  formatRatio,
  formatTime,
  frequencyPointAt,
  integer,
  magnitudeScalingAt,
  selectCatalog,
} from "../briefing-data.ts";
import { ActivityBars, Metric } from "./BriefingPrimitives.tsx";
import {
  EventAtlas,
  FrequencyMagnitudePlot,
  ImpactScatter,
} from "./BriefingVisuals.tsx";

const tempoAutoAnimate = {
  autoAnimate: true,
  autoAnimateDuration: 0.8,
  autoAnimateEasing: "cubic-bezier(0.22, 1, 0.36, 1)",
  autoAnimateId: "catalog-tempo",
  autoAnimateUnmatched: true,
} as const;

export const CoverSlide = ({ model }: { model: BriefingModel }) => (
  <Slide className="cover-slide">
    <div className="briefing-slide cover">
      <div className="cover-copy">
        <p className="deck-kicker deck-kicker-light">
          USGS weekly catalog · {formatPeriod(model.analysis?.weekly)}
        </p>
        <h1>Reading one week of earthquakes</h1>
        <p className="deck-lede">
          Compare logarithmic scale, event frequency, and the choices hidden
          inside a data filter.
        </p>
        <ol className="cover-questions" aria-label="Lesson questions">
          <li>
            <span>01</span> How much larger is a larger earthquake?
          </li>
          <li>
            <span>02</span> What changes when we move the threshold?
          </li>
          <li>
            <span>03</span> Why do the strongest events become rare?
          </li>
        </ol>
      </div>
      <div className="cover-atlas">
        <EventAtlas events={model.events} />
        <dl className="cover-readout" aria-label="Weekly catalog summary">
          <div>
            <dt>Source records</dt>
            <dd>
              {model.analysis
                ? integer.format(model.analysis.weekly.source_events)
                : "…"}
            </dd>
          </div>
          <div>
            <dt>Largest event</dt>
            <dd>
              M{model.analysis?.weekly.maximum_magnitude.toFixed(1) ?? "…"}
            </dd>
          </div>
          <div>
            <dt>Time span</dt>
            <dd>7 days</dd>
          </div>
        </dl>
      </div>
    </div>
  </Slide>
);

export const CatalogSlide = ({ model }: { model: BriefingModel }) => {
  const weekly = model.analysis?.weekly;
  const belowThreshold = weekly
    ? weekly.source_events - weekly.qualified_events
    : 0;

  return (
    <Slide
      {...tempoAutoAnimate}
    >
      <div className="briefing-slide catalog-slide">
        <header className="slide-header">
          <p className="deck-kicker">03 · From record to evidence</p>
          <h2>A catalog is a measurement lens.</h2>
          <p className="slide-intro">
            Before interpreting a pattern, separate the published feed, the
            numerical rule, and the question the learner will answer.
          </p>
        </header>

        <div className="catalog-layout">
          <div className="catalog-sequence">
            <article className="catalog-step">
              <span>Published feed</span>
              <strong>
                {weekly ? integer.format(weekly.source_events) : "…"}
              </strong>
              <p>records in the fixed USGS weekly snapshot</p>
            </article>
            <article className="catalog-step fragment" data-fragment-index="0">
              <span>Numerical rule</span>
              <strong>
                {weekly ? integer.format(weekly.qualified_events) : "…"}
              </strong>
              <p>records satisfy the computed M2.5+ threshold</p>
            </article>
            <article
              className="catalog-step catalog-step-accent fragment"
              data-fragment-index="1"
            >
              <span>Interpretation</span>
              <strong>{formatPeriod(weekly)}</strong>
              <p>one bounded observation window for linked comparisons</p>
            </article>
            <p className="catalog-footnote fragment" data-fragment-index="1">
              {belowThreshold === 1
                ? "One stored value is M2.45, which rounds to the feed’s published M2.5 threshold."
                : `${belowThreshold} source records sit below the numerical M2.5 cut.`}
            </p>
          </div>

          <div className="catalog-tempo-card">
            <div className="figure-heading">
              <h3 data-id="weekly-tempo-title">Seven days of activity</h3>
              <small>events + maximum magnitude</small>
            </div>
            <ActivityBars
              activity={model.activity}
              compact
              maximum={model.maximumDailyCount}
              peakKey={model.peakKey}
            />
          </div>
        </div>
      </div>
    </Slide>
  );
};

export const TempoSlide = ({ model }: { model: BriefingModel }) => {
  const magnitudePeak = model.activity.find((row) =>
    row.maximum_magnitude === model.maximumDailyMagnitude
  );

  return (
    <Slide
      {...tempoAutoAnimate}
    >
      <div className="briefing-slide tempo-slide">
        <header className="slide-header slide-header-split">
          <div>
            <p className="deck-kicker">04 · Time</p>
            <h2 data-id="weekly-tempo-title">
              Count and size tell different stories.
            </h2>
          </div>
          <p className="slide-intro">
            Event volume describes catalog tempo. The daily maximum isolates the
            strongest event recorded on each day.
          </p>
        </header>

        <ActivityBars
          activity={model.activity}
          maximum={model.maximumDailyCount}
          peakKey={model.peakKey}
        />

        <div className="tempo-findings">
          <Metric
            detail="highest daily count"
            label={model.peakActivity ? formatDay(model.peakActivity.day) : "…"}
            value={model.peakActivity
              ? integer.format(model.peakActivity.events)
              : "…"}
          />
          <Metric
            detail="largest daily maximum"
            label={magnitudePeak ? formatDay(magnitudePeak.day) : "…"}
            value={`M${model.maximumDailyMagnitude.toFixed(1)}`}
          />
          <blockquote>
            “Most events” and “largest event” are separate analytical claims.
          </blockquote>
        </div>
      </div>
    </Slide>
  );
};

export const MagnitudeSlide = ({ model }: { model: BriefingModel }) => {
  const magnitude = model.analysis?.magnitude;
  const comparisons = magnitude?.comparisons ?? [];
  const [reference, setReference] = useState(magnitude?.default_reference ?? 4);
  const scaling = magnitudeScalingAt(comparisons, reference);
  const minimum = comparisons[0]?.reference_magnitude ?? 2.5;
  const maximum = comparisons.at(-1)?.reference_magnitude ?? 7;

  return (
    <Slide>
      <div className="briefing-slide magnitude-slide">
        <header className="slide-header slide-header-split">
          <div>
            <p className="deck-kicker">01 · Scale</p>
            <h2>Magnitude is logarithmic, not linear.</h2>
          </div>
          <p className="slide-intro">
            Compare the week’s M{scaling?.maximum_magnitude.toFixed(1) ?? "…"}
            {" "}
            event with any reference magnitude. The equations translate their
            difference into recorded amplitude and approximate energy ratios.
          </p>
        </header>

        <div className="magnitude-layout">
          <div className="notebook-lab">
            <div className="lab-heading">
              <span>Reference magnitude</span>
              <small>Choose a comparison</small>
            </div>
            <label className="lesson-range">
              <output>M{scaling?.reference_magnitude.toFixed(1) ?? "…"}</output>
              <input
                aria-label="Comparison magnitude"
                max={maximum}
                min={minimum}
                onChange={(event) =>
                  setReference(Number(event.currentTarget.value))}
                onKeyDown={(event) => event.stopPropagation()}
                step={0.1}
                type="range"
                value={reference}
              />
              <span className="lesson-range-bounds" aria-hidden="true">
                <span>M{minimum.toFixed(1)}</span>
                <span>M{maximum.toFixed(1)}</span>
              </span>
            </label>
            <div
              className="lesson-equations"
              aria-label="Magnitude scale equations"
            >
              <span>
                A₂ / A₁ = 10<sup>ΔM</sup>
              </span>
              <span>
                E₂ / E₁ ≈ 10<sup>1.5ΔM</sup>
              </span>
            </div>
          </div>

          <div className="ratio-proof" aria-live="polite">
            <div className="ratio-equation">
              <span>Magnitude difference</span>
              <strong>ΔM = {scaling?.difference.toFixed(1) ?? "…"}</strong>
            </div>
            <div className="ratio-result ratio-result-amplitude">
              <span>Recorded amplitude</span>
              <strong>
                {scaling ? formatRatio(scaling.amplitude_ratio) : "…"}×
              </strong>
              <small>
                10<sup>ΔM</sup>
              </small>
            </div>
            <div className="ratio-result ratio-result-energy">
              <span>Released energy, approximate</span>
              <strong>
                {scaling ? formatRatio(scaling.energy_ratio) : "…"}×
              </strong>
              <small>
                10<sup>1.5ΔM</sup>
              </small>
            </div>
          </div>
        </div>
      </div>
    </Slide>
  );
};

export const FrequencySlide = ({ model }: { model: BriefingModel }) => {
  const frequency = model.analysis?.frequency;
  const fit = frequency?.model;
  const curve = frequency?.curve ?? [];
  const [magnitude, setMagnitude] = useState(
    frequency?.default_magnitude ?? 4.5,
  );
  const selected = frequencyPointAt(curve, magnitude);
  const minimum = fit?.fit_minimum ?? 3;
  const maximum = fit?.fit_maximum ?? 6;

  return (
    <Slide>
      <div className="briefing-slide frequency-slide">
        <header className="slide-header slide-header-split">
          <div>
            <p className="deck-kicker">05 · Frequency</p>
            <h2>As magnitude rises, event counts fall.</h2>
          </div>
          <p className="slide-intro">
            A logarithmic count axis turns multiplicative change into distance.
            The near-linear section is summarized by a descriptive
            frequency–magnitude fit.
          </p>
        </header>

        <div className="frequency-layout">
          <FrequencyMagnitudePlot
            curve={frequency?.curve ?? []}
            fitMaximum={maximum}
            fitMinimum={minimum}
            selectedMagnitude={selected?.magnitude ?? 4.5}
          />
          <aside className="frequency-notes">
            <div className="frequency-control-panel">
              <div className="lab-heading">
                <span>Choose a magnitude cut</span>
                <small>Explore the fitted range</small>
              </div>
              <label className="lesson-range lesson-range-compact">
                <output>M{selected?.magnitude.toFixed(1) ?? "…"}</output>
                <input
                  aria-label="Magnitude threshold"
                  max={maximum}
                  min={minimum}
                  onChange={(event) =>
                    setMagnitude(Number(event.currentTarget.value))}
                  onKeyDown={(event) => event.stopPropagation()}
                  step={0.1}
                  type="range"
                  value={magnitude}
                />
                <span className="lesson-range-bounds" aria-hidden="true">
                  <span>M{minimum.toFixed(1)}</span>
                  <span>M{maximum.toFixed(1)}</span>
                </span>
              </label>
              <div className="frequency-cut-summary" aria-live="polite">
                <span>
                  M{selected?.magnitude.toFixed(1) ?? "…"} and above
                </span>
                <dl>
                  <div>
                    <dt>Observed</dt>
                    <dd>
                      {selected ? integer.format(selected.events) : "…"}
                    </dd>
                  </div>
                  <div>
                    <dt>Fit estimate</dt>
                    <dd>
                      {selected
                        ? integer.format(Math.round(selected.fitted_events))
                        : "…"}
                    </dd>
                  </div>
                </dl>
              </div>
            </div>
            <dl className="fit-readout">
              <div>
                <dt>Estimated b</dt>
                <dd>{fit?.b_value.toFixed(2) ?? "…"}</dd>
              </div>
              <div>
                <dt>Fit R²</dt>
                <dd>{fit?.r_squared.toFixed(2) ?? "…"}</dd>
              </div>
              <div>
                <dt>Fit range</dt>
                <dd>
                  M{fit?.fit_minimum.toFixed(1) ??
                    "…"}–{fit?.fit_maximum.toFixed(1) ?? "…"}
                </dd>
              </div>
            </dl>
            <p className="method-caveat">
              One global week · descriptive fit.
            </p>
          </aside>
        </div>
      </div>
    </Slide>
  );
};

export const SelectionSlide = ({ model }: { model: BriefingModel }) => {
  const [minimumMagnitude, setMinimumMagnitude] = useState(2.5);
  const [status, setStatus] = useState("All statuses");
  const selection = model.analysis
    ? selectCatalog(model.analysis.events, minimumMagnitude, status)
    : undefined;
  const summary = selection?.summary;
  const total = model.analysis?.weekly.source_events ?? 0;
  const share = total > 0 && summary ? summary.events / total : 0;
  const maximumMagnitude = model.analysis?.weekly.maximum_magnitude ?? 7;
  const statuses = [
    "All statuses",
    ...new Set(model.events.map((event) => event.status).sort()),
  ];

  return (
    <Slide>
      <div className="briefing-slide selection-slide">
        <header className="slide-header slide-header-split">
          <div>
            <p className="deck-kicker">02 · Selection</p>
            <h2>A threshold redraws the population.</h2>
          </div>
          <p className="slide-intro">
            Adjust the threshold to define which records enter the comparison.
            Muted points preserve the full catalog while the selected set
            updates.
          </p>
        </header>

        <div className="selection-layout">
          <aside className="selection-controls">
            <div className="lab-heading">
              <span>Define the population</span>
              <small>Adjust the threshold</small>
            </div>
            <label className="lesson-range lesson-range-compact">
              <output>M{minimumMagnitude.toFixed(1)}</output>
              <input
                aria-label="Minimum magnitude"
                max={maximumMagnitude}
                min={2.5}
                onChange={(event) =>
                  setMinimumMagnitude(Number(event.currentTarget.value))}
                onKeyDown={(event) => event.stopPropagation()}
                step={0.1}
                type="range"
                value={minimumMagnitude}
              />
              <span className="lesson-range-bounds" aria-hidden="true">
                <span>M2.5</span>
                <span>M{maximumMagnitude.toFixed(1)}</span>
              </span>
            </label>
            <label className="lesson-select">
              <span>Review status</span>
              <select
                aria-label="Review status"
                onChange={(event) => setStatus(event.currentTarget.value)}
                onKeyDown={(event) => event.stopPropagation()}
                value={status}
              >
                {statuses.map((option) => <option key={option}>{option}
                </option>)}
              </select>
            </label>
            <div className="selection-summary" aria-live="polite">
              <span>Current analytical set</span>
              <strong>{summary ? integer.format(summary.events) : "…"}</strong>
              <p>
                M{summary?.minimum_magnitude.toFixed(1) ?? "…"}+ ·{" "}
                {summary?.status.toLowerCase() ?? "loading"}
              </p>
              <div className="selection-share">
                <span style={{ width: `${share * 100}%` }} />
              </div>
              <small>
                {Math.round(share * 100)}% of source records retained
              </small>
            </div>
            <dl className="selection-facts">
              <div>
                <dt>Largest selected</dt>
                <dd>M{summary?.maximum_magnitude.toFixed(1) ?? "…"}</dd>
              </div>
              <div>
                <dt>Felt reports</dt>
                <dd>{summary ? integer.format(summary.felt_reports) : "…"}</dd>
              </div>
              <div>
                <dt>Tsunami flags</dt>
                <dd>{summary?.tsunami_flags ?? "…"}</dd>
              </div>
            </dl>
          </aside>

          <div className="selection-map">
            <EventAtlas
              events={selection?.events ?? model.events}
              variant="selection"
            />
          </div>
        </div>
      </div>
    </Slide>
  );
};

export const ImpactSlide = ({ model }: { model: BriefingModel }) => {
  const mostFelt = model.events.reduce<
    (typeof model.events)[number] | undefined
  >(
    (current, event) =>
      !current || (event.felt ?? 0) > (current.felt ?? 0) ? event : current,
    undefined,
  );

  return (
    <Slide>
      <div className="briefing-slide impact-slide">
        <header className="slide-header slide-header-split">
          <div>
            <p className="deck-kicker">06 · Consequence</p>
            <h2>Magnitude and observed impact are not interchangeable.</h2>
          </div>
          <p className="slide-intro">
            Magnitude describes the earthquake. Felt reports describe a human
            response shaped by exposure, access, and reporting behavior.
          </p>
        </header>

        <div className="impact-layout">
          <ImpactScatter events={model.events} />
          <aside className="event-casebook">
            <article>
              <span>Largest event</span>
              <strong>
                M{model.primaryEvent?.magnitude.toFixed(1) ?? "…"}
              </strong>
              <h3>{model.primaryEvent?.place ?? "Loading event"}</h3>
              <p>
                {model.primaryEvent
                  ? `${formatTime(model.primaryEvent.time)} · ${
                    feltLabel(model.primaryEvent.felt)
                  }`
                  : "Event context loading"}
              </p>
            </article>
            <article>
              <span>Most reported</span>
              <strong>{integer.format(mostFelt?.felt ?? 0)}</strong>
              <h3>{mostFelt?.place ?? "Loading event"}</h3>
              <p>
                {mostFelt
                  ? `M${mostFelt.magnitude.toFixed(1)} · ${
                    formatTime(mostFelt.time)
                  }`
                  : "Event context loading"}
              </p>
            </article>
          </aside>
        </div>
      </div>
    </Slide>
  );
};
