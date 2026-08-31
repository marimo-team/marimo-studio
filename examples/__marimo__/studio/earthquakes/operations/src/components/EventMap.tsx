// @deno-types="npm:@types/react@19.2.10"
import { useMemo, useState } from "react";
import * as maplibregl from "maplibre-gl";
import MapView, {
  AttributionControl,
  Marker,
  NavigationControl,
  Popup,
} from "react-map-gl/maplibre";

import { BASEMAP_STYLE } from "../map-style.ts";
import { type EarthquakeEvent, formatMagnitude } from "../operations-data.ts";

interface EventMapProps {
  events: readonly EarthquakeEvent[];
  loading: boolean;
  selectedEvent: EarthquakeEvent | null;
  onSelect: (id: string | null) => void;
}

export const EventMap = ({
  events,
  loading,
  selectedEvent,
  onSelect,
}: EventMapProps) => {
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const eventIndex = useMemo(
    () => new Map(events.map((event) => [event.id, event])),
    [events],
  );
  const hoveredEvent = eventIndex.get(hoveredId ?? "") ?? null;

  return (
    <section className="map-panel" aria-labelledby="map-title">
      <header className="map-heading">
        <div>
          <p className="eyebrow">Spatial situation</p>
          <h2 id="map-title">Filtered epicenters</h2>
        </div>
        <div className="map-actions">
          <div className="map-legend" aria-label="Map legend">
            <span>
              <i className="marker-standard" /> Event
            </span>
            <span>
              <i className="marker-major" /> M5+
            </span>
            <span>
              <i className="marker-tsunami" /> Tsunami flag
            </span>
          </div>
          <label className="event-picker">
            <span>Selected event</span>
            <select
              value={selectedEvent?.id ?? ""}
              onChange={(event) => onSelect(event.currentTarget.value || null)}
            >
              <option value="">No event selected</option>
              {events.map((event) => (
                <option key={event.id} value={event.id}>
                  M {formatMagnitude(event.magnitude)} · {event.place}
                </option>
              ))}
            </select>
          </label>
        </div>
      </header>
      <div
        className="map-stage"
        role="region"
        aria-label="Interactive earthquake map"
      >
        <MapView
          mapLib={maplibregl}
          initialViewState={{ longitude: 0, latitude: 18, zoom: 1.15 }}
          mapStyle={BASEMAP_STYLE}
          attributionControl={false}
          cooperativeGestures
          cursor={hoveredEvent ? "pointer" : "grab"}
          onLoad={(event) => {
            requestAnimationFrame(() => event.target.resize());
          }}
          onClick={() => onSelect(null)}
        >
          <NavigationControl position="top-right" showCompass={false} />
          <AttributionControl position="bottom-right" compact />
          {events.map((event) => {
            const markerSize = Math.min(
              18,
              Math.max(6, 5 + (event.magnitude - 2) * 3),
            );
            return (
              <Marker
                key={event.id}
                longitude={event.longitude}
                latitude={event.latitude}
                anchor="center"
              >
                <span
                  className={`event-marker${
                    event.tsunami
                      ? " event-marker-alert"
                      : event.magnitude >= 5
                      ? " event-marker-major"
                      : ""
                  }${event.id === selectedEvent?.id ? " is-selected" : ""}`}
                  title={`M ${
                    formatMagnitude(
                      event.magnitude,
                    )
                  }, ${event.place}`}
                  style={{
                    width: `${markerSize}px`,
                    height: `${markerSize}px`,
                  }}
                  onMouseEnter={() => setHoveredId(event.id)}
                  onMouseLeave={() => setHoveredId(null)}
                  onClick={(clickEvent) => {
                    clickEvent.stopPropagation();
                    onSelect(event.id);
                  }}
                />
              </Marker>
            );
          })}
          {selectedEvent
            ? (
              <Popup
                longitude={selectedEvent.longitude}
                latitude={selectedEvent.latitude}
                anchor="bottom"
                offset={12}
                closeOnClick={false}
                onClose={() => onSelect(null)}
              >
                <strong>M{formatMagnitude(selectedEvent.magnitude)}</strong>
                <span>{selectedEvent.place}</span>
              </Popup>
            )
            : null}
        </MapView>

        {loading
          ? (
            <div className="map-loader" role="status">
              <span className="map-loader-signal" aria-hidden="true">
                <i />
                <i />
                <i />
              </span>
              Preparing epicenter map
            </div>
          )
          : events.length === 0
          ? (
            <div className="map-empty">
              No epicenters match the current filter.
            </div>
          )
          : null}
        {hoveredEvent
          ? (
            <div className="hover-readout" aria-hidden="true">
              <strong>M{formatMagnitude(hoveredEvent.magnitude)}</strong>
              <span>{hoveredEvent.place}</span>
            </div>
          )
          : null}
      </div>
    </section>
  );
};
