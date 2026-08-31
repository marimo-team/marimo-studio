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
  event: EarthquakeEvent | null;
  loading: boolean;
}

export const EventDetails = ({ event, loading }: EventDetailsProps) => (
  <aside
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
            <div>
              <dt>Observed</dt>
              <dd>{formatEventTime(event.time)}</dd>
            </div>
            <div>
              <dt>Felt reports</dt>
              <dd>{formatInteger(event.felt)}</dd>
            </div>
            <div>
              <dt>Significance</dt>
              <dd>{formatInteger(event.significance)}</dd>
            </div>
            <div>
              <dt>Review status</dt>
              <dd>{event.status}</dd>
            </div>
            <div>
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
