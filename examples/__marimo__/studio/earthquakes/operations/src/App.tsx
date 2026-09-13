/// <reference path="./marimo-studio.d.ts" />

// @deno-types="npm:@types/react@19.2.10"
import { useMemo, useState } from "react";

import { EventDetails, PriorityEvents } from "./components/EventDetails.tsx";
import { EventMap } from "./components/EventMap.tsx";
import {
  type EarthquakeEvent,
  type EventSummary,
  formatInteger,
  formatMagnitude,
  rankEvents,
} from "./operations-data.ts";
import { type MarimoTable, useMarimoValue } from "./lib/use-marimo-value.ts";

const METRICS = [
  { key: "events", label: "Events" },
  { key: "maximum_magnitude", label: "Max magnitude" },
  { key: "felt_reports", label: "Felt reports" },
  { key: "tsunami_flags", label: "Tsunami flags" },
] as const;

export const App = () => {
  const {
    error: eventsError,
    hostRef: eventsHostRef,
    value: filteredEvents,
  } = useMarimoValue<MarimoTable<EarthquakeEvent>>("filtered_events");
  const {
    error: summaryError,
    hostRef: summaryHostRef,
    value: eventSummary,
  } = useMarimoValue<EventSummary>("event_summary");
  const [selectedId, setSelectedId] = useState<string | null | undefined>(
    undefined,
  );

  const events = useMemo(
    () => filteredEvents?.toArray() ?? [],
    [filteredEvents],
  );
  const priorityEvents = useMemo(
    () => rankEvents(events, eventSummary?.priority_count ?? 0),
    [eventSummary?.priority_count, events],
  );
  const selectedEvent = selectedId === null
    ? null
    : (events.find((event) => event.id === selectedId) ??
      priorityEvents[0] ??
      null);
  const hasError = eventsError || summaryError;
  const isLoading =
    (filteredEvents === undefined || eventSummary === undefined) && !hasError;
  const maximumMagnitude = eventSummary?.events === 0
    ? "n/a"
    : formatMagnitude(eventSummary?.maximum_magnitude);
  const statusText = hasError
    ? "Event data unavailable"
    : isLoading
    ? "Loading weekly events"
    : `${formatInteger(events.length)} events on map`;

  return (
    <>
      <span
        ref={eventsHostRef}
        aria-hidden="true"
        hidden
        id="events-data"
        mo-value="filtered_events"
      />
      <span
        ref={summaryHostRef}
        aria-hidden="true"
        hidden
        id="summary-data"
        mo-value="event_summary"
      />

      <main
        data-marimo-lens-inputs="events-data summary-data"
        className="operations-shell"
        aria-busy={isLoading}
      >
        <header className="operations-header">
          <div>
            <p className="eyebrow">
              USGS weekly feed · {eventSummary
                ? `Global M${formatMagnitude(eventSummary.minimum_magnitude)}+`
                : "Global catalog"}
            </p>
            <h1>Earthquake operations</h1>
          </div>
          <div
            className={`filter-status${isLoading ? " is-loading" : ""}`}
            aria-label="Active event filter"
          >
            <span aria-hidden="true" />
            {eventSummary
              ? `M${
                eventSummary.minimum_magnitude.toFixed(
                  1,
                )
              }+ · ${eventSummary.status}`
              : "Awaiting filter state"}
          </div>
        </header>

        <p className="data-status" role="status" aria-live="polite">
          {statusText}
        </p>

        <section
          data-marimo-lens-inputs="summary-data"
          className="metric-strip"
          aria-label="Current situation metrics"
        >
          {METRICS.map(({ key, label }) => (
            <article key={key}>
              <span
                hidden
                mo-value={`event_summary.${key}`}
                data-marimo-allow="*"
              />
              {key === "maximum_magnitude" && (
                <span hidden mo-value="event_summary.events" />
              )}
              <span>{label}</span>
              <strong>
                {key === "maximum_magnitude"
                  ? maximumMagnitude
                  : formatInteger(eventSummary?.[key])}
              </strong>
            </article>
          ))}
        </section>

        {hasError
          ? (
            <div className="error-banner" role="alert">
              Event data could not be loaded. Reload the page to retry.
            </div>
          )
          : null}

        <section className="notebook-controls" aria-labelledby="controls-title">
          <div className="section-heading">
            <p className="eyebrow">Review scope</p>
            <h2 id="controls-title">Situation filter</h2>
          </div>
          <marimo-cell name="event_controls" />
        </section>

        <div className="operations-workspace">
          <aside className="control-rail" aria-label="Priority events">
            <PriorityEvents
              events={priorityEvents}
              loading={isLoading}
              selectedId={selectedEvent?.id ?? null}
              onSelect={setSelectedId}
            />
          </aside>

          <EventMap
            events={events}
            loading={isLoading}
            priorityMagnitude={eventSummary?.priority_magnitude}
            selectedEvent={selectedEvent}
            onSelect={setSelectedId}
          />
          <EventDetails
            event={selectedEvent}
            index={events.findIndex((event) => event.id === selectedEvent?.id)}
            loading={isLoading}
          />
        </div>

        <footer className="operations-footer">
          Fixed USGS weekly snapshot · Positions show epicenters · Marker size
          encodes magnitude
        </footer>
      </main>
    </>
  );
};
