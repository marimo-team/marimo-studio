import {
  type EarthquakeEvent,
  formatEventTime,
  formatInteger,
  formatMagnitude,
} from "../operations-data.ts";

interface PriorityEventsProps {
  events: readonly EarthquakeEvent[];
  loading: boolean;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}

export const PriorityEvents = ({
  events,
  loading,
  selectedId,
  onSelect,
}: PriorityEventsProps) => (
  <section
    data-marimo-lens-inputs="events-data summary-data"
    className="panel-section priority-section"
    aria-labelledby="priority-title"
  >
    <div className="section-heading">
      <p className="eyebrow">Ranked by magnitude</p>
      <h2 id="priority-title">Priority events</h2>
    </div>
    {loading
      ? (
        <div className="event-list-loader" aria-hidden="true">
          <i />
          <i />
          <i />
          <i />
          <i />
          <i />
        </div>
      )
      : events.length > 0
      ? (
        <ol className="event-list">
          {events.map((event) => (
            <li key={event.id}>
              <button
                data-marimo-lens-inputs="events-data"
                data-marimo-lens-label={event.place}
                type="button"
                aria-pressed={event.id === selectedId}
                onClick={() => onSelect(event.id)}
              >
                <strong>M{formatMagnitude(event.magnitude)}</strong>
                <span>{event.place}</span>
                <small>{formatEventTime(event.time)}</small>
              </button>
            </li>
          ))}
        </ol>
      )
      : <p className="empty-copy">No events match the current filter.</p>}
  </section>
);

interface EventDetailsProps {
  index: number;
  event: EarthquakeEvent | null;
  loading: boolean;
}

export const EventDetails = ({ event, index, loading }: EventDetailsProps) => (
  <aside
    data-marimo-lens-inputs="events-data"
    className="detail-panel"
    aria-labelledby="detail-title"
    aria-live="polite"
  >
    <div className="section-heading">
      <p className="eyebrow">Selected event</p>
      <h2 id="detail-title">
        {loading
          ? "Loading event"
          : event
          ? `Magnitude ${formatMagnitude(event.magnitude)}`
          : "No selection"}
      </h2>
    </div>
    {loading
      ? (
        <div className="detail-loader" aria-hidden="true">
          <i />
          <i />
          <i />
          <i />
        </div>
      )
      : event
      ? (
        <>
          <p className="event-place">{event.place}</p>
          <dl className="event-facts">
            <div data-marimo-lens-inputs="event-time-data">
              <marimo-output
                id="event-time-data"
                hidden
                value={`filtered_events["time"][${index}]`}
                data-marimo-allow="*"
              />
              <dt>Observed</dt>
              <dd>{formatEventTime(event.time)}</dd>
            </div>
            <div>
              <span
                hidden
                mo-value={`filtered_events["felt"][${index}]`}
                data-marimo-allow="*"
              />
              <dt>Felt reports</dt>
              <dd>{formatInteger(event.felt)}</dd>
            </div>
            <div>
              <span
                hidden
                mo-value={`filtered_events["significance"][${index}]`}
                data-marimo-allow="*"
              />
              <dt>Significance</dt>
              <dd>{formatInteger(event.significance)}</dd>
            </div>
            <div>
              <span
                hidden
                mo-value={`filtered_events["status"][${index}]`}
                data-marimo-allow="*"
              />
              <dt>Review status</dt>
              <dd>{event.status}</dd>
            </div>
            <div>
              <span
                hidden
                mo-value={`filtered_events["tsunami"][${index}]`}
                data-marimo-allow="*"
              />
              <dt>Tsunami flag</dt>
              <dd className={event.tsunami ? "alert-value" : undefined}>
                {event.tsunami ? "Flagged" : "None"}
              </dd>
            </div>
          </dl>
          <a
            className="source-link"
            href={event.url}
            target="_blank"
            rel="noreferrer"
          >
            Open USGS event record
          </a>
        </>
      )
      : (
        <p className="empty-copy">
          Choose a priority event or select a point on the map.
        </p>
      )}
  </aside>
);
