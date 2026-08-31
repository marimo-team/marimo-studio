import { Slide } from "@revealjs/react";
import {
  type BriefingModel,
  concisePlace,
  feltLabel,
  formatDay,
  formatPeriod,
  formatTime,
  integer,
} from "../briefing-data.ts";
import { ActivityBars, Metric } from "./BriefingPrimitives.tsx";

const autoAnimate = {
  autoAnimate: true,
  autoAnimateId: "weekly-tempo",
  autoAnimateDuration: 0.85,
  autoAnimateEasing: "cubic-bezier(0.77, 0, 0.175, 1)",
  autoAnimateUnmatched: true,
} as const;

export const CoverSlide = ({ model }: { model: BriefingModel }) => (
  <Slide
    className="cover-slide"
    backgroundColor="#111111"
    transition="fade"
  >
    <div className="briefing-slide cover">
      <p className="deck-kicker">
        USGS · Global M2.5+ · {formatPeriod(model.weekly)}
      </p>
      <div className="cover-title">
        <h1>Weekly seismic situation update</h1>
        <p className="deck-lede">
          Global activity, felt reports, tsunami flags, and events for the next
          duty team.
        </p>
      </div>
      <footer className="cover-meta">
        <span>Duty handover</span>
        <span>
          {model.weekly
            ? `${integer.format(model.weekly.source_events)} source events`
            : "Weekly source record"}
        </span>
      </footer>
    </div>
  </Slide>
);

export const ExecutiveSlide = ({ model }: { model: BriefingModel }) => (
  <Slide {...autoAnimate}>
    <div className="briefing-slide executive">
      <header className="slide-header">
        <p className="deck-kicker">01 · Executive assessment</p>
        <h2>
          {model.primaryEvent
            ? `A magnitude ${
              model.primaryEvent.magnitude.toFixed(1)
            } event near ${
              concisePlace(model.primaryEvent.place)
            } drove the week’s response priorities.`
            : "The largest event drove the week’s response priorities."}
        </h2>
      </header>

      <div className="executive-frame">
        <div className="executive-metrics">
          <Metric
            label="source events"
            value={model.weekly
              ? integer.format(model.weekly.source_events)
              : "…"}
          />
          <Metric
            label="reported magnitude"
            value={model.weekly
              ? integer.format(model.weekly.qualified_events)
              : "…"}
          />
          <Metric
            label="maximum magnitude"
            value={model.weekly?.maximum_magnitude.toFixed(1) ?? "…"}
          />
          <Metric
            label="felt reports"
            value={model.weekly
              ? integer.format(model.weekly.felt_reports)
              : "…"}
          />
        </div>

        <div className="tempo-card">
          <div className="tempo-card-heading">
            <h3 data-id="weekly-tempo-title">Weekly rhythm</h3>
            <span>
              {model.weekly
                ? `${model.weekly.tsunami_flags} tsunami flags`
                : "Loading"}
            </span>
          </div>
          <ActivityBars
            activity={model.activity}
            compact
            maximum={model.maximumDailyCount}
            peakKey={model.peakKey}
          />
        </div>
      </div>

      <footer className="slide-footer">
        USGS weekly record · {formatPeriod(model.weekly)}
      </footer>
    </div>
  </Slide>
);

export const TempoSlide = ({ model }: { model: BriefingModel }) => (
  <Slide {...autoAnimate}>
    <div className="briefing-slide tempo-detail">
      <header className="slide-header">
        <p className="deck-kicker">02 · Weekly rhythm</p>
        <h2 data-id="weekly-tempo-title">Weekly rhythm</h2>
        <p className="slide-intro">
          {model.peakActivity
            ? `Volume peaked on ${formatDay(model.peakActivity.day)} with ${
              integer.format(model.peakActivity.events)
            } recorded events.`
            : "Daily activity is loading."}
        </p>
      </header>

      <ActivityBars
        activity={model.activity}
        maximum={model.maximumDailyCount}
        peakKey={model.peakKey}
      />

      <footer className="slide-footer slide-footer-split">
        <span>
          {model.peakActivity
            ? `Peak activity · ${formatDay(model.peakActivity.day)} · ${
              integer.format(model.peakActivity.events)
            } events`
            : "Peak activity loading"}
        </span>
        <span>
          Largest daily maximum · M{model.maximumDailyMagnitude.toFixed(1)}
        </span>
      </footer>
    </div>
  </Slide>
);

export const OperatingPictureSlide = (
  { model }: { model: BriefingModel },
) => (
  <Slide>
    <div className="briefing-slide operating-picture">
      <header className="slide-header">
        <p className="deck-kicker">03 · Operating picture</p>
        <h2>Set the review cut for the current handover.</h2>
      </header>

      <div className="operating-frame">
        <div className="control-block">
          <span className="frame-label">Review filters</span>
          <marimo-cell name="event_controls" />
        </div>

        <div
          className={model.summary?.tsunami_flags
            ? "selected-situation selected-situation-alert"
            : "selected-situation"}
          aria-live="polite"
          aria-label="Selected review cut"
          role="region"
        >
          <div className="selected-heading">
            <span className="frame-label">Selected review cut</span>
            <strong>
              M{model.summary?.minimum_magnitude.toFixed(1) ?? "…"}+ ·{" "}
              {model.summary?.status.toLowerCase() ?? "loading"}
            </strong>
          </div>
          <div className="selected-metrics">
            <Metric
              label="selected events"
              value={model.summary ? integer.format(model.summary.events) : "…"}
            />
            <Metric
              label="maximum magnitude"
              value={model.summary?.maximum_magnitude.toFixed(1) ?? "…"}
            />
            <Metric
              label="felt reports"
              value={model.summary
                ? integer.format(model.summary.felt_reports)
                : "…"}
            />
            <Metric
              label="tsunami flags"
              value={model.summary?.tsunami_flags ?? "…"}
            />
          </div>
        </div>
      </div>

      <footer className="slide-footer">
        Full week · {model.weekly
          ? `${integer.format(model.weekly.source_events)} events · Maximum M${
            model.weekly.maximum_magnitude.toFixed(1)
          }`
          : "Loading weekly totals"}
      </footer>
    </div>
  </Slide>
);

export const WatchlistSlide = ({ model }: { model: BriefingModel }) => (
  <Slide>
    <div className="briefing-slide watchlist-slide">
      <header className="slide-header">
        <p className="deck-kicker">04 · Priority watchlist</p>
        <h2>
          {model.primaryEvent
            ? `M ${model.primaryEvent.magnitude.toFixed(1)} near ${
              concisePlace(model.primaryEvent.place)
            } leads the watch sequence.`
            : "Priority events are loading."}
        </h2>
      </header>

      <div className="watch-layout">
        <article className="watch-feature">
          <span className="frame-label">Primary event</span>
          <strong className="feature-magnitude">
            M {model.primaryEvent?.magnitude.toFixed(1) ?? "…"}
          </strong>
          <h3>{model.primaryEvent?.place ?? "Loading event record"}</h3>
          <p>
            {model.primaryEvent
              ? `${formatTime(model.primaryEvent.time)} · ${
                feltLabel(model.primaryEvent.felt)
              }`
              : "Waiting for event details"}
          </p>
          {model.primaryEvent?.tsunami
            ? <span className="event-alert">Tsunami flag</span>
            : null}
        </article>

        <ol className="watch-list">
          {model.strongest.slice(1).map((event, index) => (
            <li key={event.id}>
              <span className="watch-rank">
                {String(index + 2).padStart(2, "0")}
              </span>
              <strong>M {event.magnitude.toFixed(1)}</strong>
              <span className="watch-place">{event.place}</span>
              <small>
                {feltLabel(event.felt)}
                {event.tsunami ? " · Tsunami flag" : ""}
              </small>
            </li>
          ))}
        </ol>
      </div>

      <footer className="slide-footer">
        Ranked by magnitude, then source significance.
      </footer>
    </div>
  </Slide>
);

export const HandoffSlide = () => (
  <Slide>
    <div className="briefing-slide handoff-slide">
      <header className="slide-header">
        <p className="deck-kicker">05 · Duty handover</p>
        <h2>
          Keep the largest event on watch. Escalate new impact signals.
        </h2>
      </header>

      <div className="handoff-layout">
        <div className="conclusion-card">
          <marimo-cell name="conclusion" />
        </div>
        <div className="handoff-actions">
          <article>
            <span>Monitor</span>
            <p>
              Review updates for the largest event and nearby sequence.
            </p>
          </article>
          <article>
            <span>Escalate</span>
            <p>Any new tsunami flag or sharp rise in felt reports.</p>
          </article>
          <article>
            <span>Follow-up</span>
            <p>Operations for event follow-up. Story for broader context.</p>
          </article>
        </div>
      </div>

      <footer className="slide-footer">
        Source event links remain available for the next duty team.
      </footer>
    </div>
  </Slide>
);
