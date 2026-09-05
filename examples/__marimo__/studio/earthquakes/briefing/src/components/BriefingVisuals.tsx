// @deno-types="npm:@types/d3-geo@3.1.0"
import { geoEqualEarth, geoGraticule10, geoPath } from "d3-geo";
// @deno-types="npm:@types/d3-scale@4.0.9"
import { scaleLinear, scaleSqrt, scaleSymlog } from "d3-scale";
// @deno-types="npm:@types/d3-shape@3.2.0"
import { curveMonotoneX, line } from "d3-shape";
import {
  type EarthquakeEvent,
  type FrequencyPoint,
  integer,
} from "../briefing-data.ts";

const sphere = { type: "Sphere" } as const;
const frequencyMargin = { top: 24, right: 22, bottom: 52, left: 72 };
const frequencyYTicks = [0, 1, 2];
const magnitudeTicks = [2.5, 3.5, 4.5, 5.5, 6.5];
const impactMargin = { top: 26, right: 30, bottom: 55, left: 72 };
const impactYTickCandidates = [0, 10, 100, 500];
const regionLabels: Array<{ label: string; coordinates: [number, number] }> = [
  { label: "NORTH AMERICA", coordinates: [-108, 42] },
  { label: "SOUTH AMERICA", coordinates: [-61, -24] },
  { label: "EUROPE", coordinates: [13, 49] },
  { label: "AFRICA", coordinates: [19, 3] },
  { label: "ASIA", coordinates: [92, 42] },
  { label: "OCEANIA", coordinates: [139, -24] },
];

export const EventAtlas = ({
  events,
  minimumMagnitude,
  variant = "overview",
}: {
  events: EarthquakeEvent[];
  minimumMagnitude: number;
  variant?: "overview" | "selection";
}) => {
  const width = 900;
  const height = 440;
  const projection = geoEqualEarth().fitExtent(
    [[18, 18], [width - 18, height - 18]],
    sphere,
  );
  const path = geoPath(projection);
  const radius = scaleSqrt().domain([2.5, 7]).range([1.8, 8.5]).clamp(true);
  const selected = events.filter((event) => event.selected);
  const primary = events[0];
  const drawnEvents = events.toSorted(
    (left, right) => left.magnitude - right.magnitude,
  );

  return (
    <figure className={`event-atlas event-atlas-${variant}`}>
      <svg
        aria-label={variant === "selection"
          ? `Global epicenter map with ${selected.length} selected events from ${events.length} source records`
          : `Global epicenter map of ${events.length} weekly earthquake records`}
        role="img"
        viewBox={`0 0 ${width} ${height}`}
      >
        <desc>
          Epicenters are positioned by longitude and latitude. Point size
          encodes earthquake magnitude. The largest event is labeled directly.
        </desc>
        <path className="atlas-sphere" d={path(sphere) ?? undefined} />
        <path
          className="atlas-graticule"
          d={path(geoGraticule10()) ?? undefined}
        />
        {regionLabels.map(({ label, coordinates }) => {
          const point = projection(coordinates);
          return point
            ? (
              <text
                className="atlas-region-label"
                key={label}
                textAnchor="middle"
                x={point[0]}
                y={point[1]}
              >
                {label}
              </text>
            )
            : null;
        })}
        {drawnEvents.map((event) => {
          const point = projection([event.longitude, event.latitude]);
          if (!point) return null;
          const isPrimary = event.id === primary?.id;
          const state = variant === "selection"
            ? event.selected ? "selected" : "context"
            : event.magnitude >= 5
            ? "major"
            : "standard";
          return (
            <circle
              className={`atlas-event atlas-event-${state}${
                isPrimary ? " atlas-event-primary" : ""
              }`}
              cx={point[0]}
              cy={point[1]}
              data-id={`event-point-${event.id}`}
              key={event.id}
              r={radius(event.magnitude)}
            >
              <title>
                M{event.magnitude.toFixed(1)} · {event.place}
              </title>
            </circle>
          );
        })}
        {primary
          ? (() => {
            const point = projection([primary.longitude, primary.latitude]);
            if (!point) return null;
            const [x, y] = point;
            const labelOnLeft = x > width * 0.66;
            const labelX = labelOnLeft ? x - 24 : x + 24;
            return (
              <g className="atlas-annotation">
                <line x1={x} x2={labelX} y1={y} y2={y - 28} />
                <circle cx={x} cy={y} r={radius(primary.magnitude) + 5} />
                <text
                  textAnchor={labelOnLeft ? "end" : "start"}
                  x={labelX}
                  y={y - 34}
                >
                  <tspan className="atlas-annotation-value">
                    M{primary.magnitude.toFixed(1)}
                  </tspan>
                  <tspan
                    className="atlas-annotation-place"
                    dy="1.4em"
                    x={labelX}
                  >
                    {primary.place}
                  </tspan>
                </text>
              </g>
            );
          })()
          : null}
      </svg>
      <figcaption>
        <span>
          <i className="atlas-key atlas-key-small" /> M{minimumMagnitude.toFixed(1)}
        </span>
        <span>
          <i className="atlas-key atlas-key-large" /> M7.0
        </span>
        {variant === "selection"
          ? (
            <span className="atlas-selection-key">
              <i className="atlas-key atlas-key-selected" /> Selected events
            </span>
          )
          : <span>Point area follows magnitude</span>}
      </figcaption>
    </figure>
  );
};

export const FrequencyMagnitudePlot = ({
  curve,
  fitMaximum,
  fitMinimum,
  selectedMagnitude,
}: {
  curve: FrequencyPoint[];
  fitMaximum: number;
  fitMinimum: number;
  selectedMagnitude: number;
}) => {
  const width = 780;
  const height = 430;
  const x = scaleLinear()
    .domain([
      Math.min(2.5, ...curve.map((point) => point.magnitude)),
      Math.max(7, ...curve.map((point) => point.magnitude)),
    ])
    .range([frequencyMargin.left, width - frequencyMargin.right]);
  const y = scaleLinear()
    .domain([0, Math.max(2.6, ...curve.map((point) => point.log10_events))])
    .range([height - frequencyMargin.bottom, frequencyMargin.top]);
  const observedPath = line<FrequencyPoint>()
    .x((point) => x(point.magnitude))
    .y((point) => y(point.log10_events))
    .curve(curveMonotoneX)(curve);
  const fitCurve = curve.filter((point) =>
    point.magnitude >= fitMinimum && point.magnitude <= fitMaximum
  );
  const fitPath = line<FrequencyPoint>()
    .x((point) => x(point.magnitude))
    .y((point) => y(point.fitted_log10_events))(fitCurve);
  const visiblePoints = curve.filter((_, index) => index % 2 === 0);

  return (
    <figure className="frequency-figure">
      <svg
        aria-label="Cumulative earthquake counts decrease with increasing magnitude on a logarithmic count scale"
        role="img"
        viewBox={`0 0 ${width} ${height}`}
      >
        <desc>
          Observed cumulative counts are shown as a solid line. A descriptive
          fit from magnitude {fitMinimum.toFixed(1)} to {fitMaximum.toFixed(1)}
          is shown as a dashed line.
        </desc>
        {frequencyYTicks.map((tick) => (
          <g key={tick}>
            <line
              className="plot-gridline"
              x1={frequencyMargin.left}
              x2={width - frequencyMargin.right}
              y1={y(tick)}
              y2={y(tick)}
            />
            <text
              className="plot-tick"
              textAnchor="end"
              x={frequencyMargin.left - 14}
              y={y(tick) + 5}
            >
              {integer.format(10 ** tick)}
            </text>
          </g>
        ))}
        {magnitudeTicks.map((tick) => (
          <g key={tick}>
            <line
              className="plot-tick-mark"
              x1={x(tick)}
              x2={x(tick)}
              y1={height - frequencyMargin.bottom}
              y2={height - frequencyMargin.bottom + 7}
            />
            <text
              className="plot-tick"
              textAnchor="middle"
              x={x(tick)}
              y={height - frequencyMargin.bottom + 28}
            >
              {tick.toFixed(1)}
            </text>
          </g>
        ))}
        <line
          className="plot-axis"
          x1={frequencyMargin.left}
          x2={frequencyMargin.left}
          y1={frequencyMargin.top}
          y2={height - frequencyMargin.bottom}
        />
        <line
          className="plot-axis"
          x1={frequencyMargin.left}
          x2={width - frequencyMargin.right}
          y1={height - frequencyMargin.bottom}
          y2={height - frequencyMargin.bottom}
        />
        <path className="frequency-observed" d={observedPath ?? undefined} />
        <path className="frequency-fit" d={fitPath ?? undefined} />
        {visiblePoints.map((point) => (
          <circle
            className="frequency-point"
            cx={x(point.magnitude)}
            cy={y(point.log10_events)}
            key={point.magnitude}
            r="3.2"
          >
            <title>
              M{point.magnitude.toFixed(1)}+: {point.events} events
            </title>
          </circle>
        ))}
        <line
          className="frequency-selection"
          x1={x(selectedMagnitude)}
          x2={x(selectedMagnitude)}
          y1={frequencyMargin.top}
          y2={height - frequencyMargin.bottom}
        />
        <text
          className="frequency-selection-label"
          textAnchor="middle"
          x={x(selectedMagnitude)}
          y={frequencyMargin.top + 4}
        >
          current cut · M{selectedMagnitude.toFixed(1)}+
        </text>
        <text
          className="plot-axis-title"
          textAnchor="middle"
          x={(frequencyMargin.left + width - frequencyMargin.right) / 2}
          y={height - 8}
        >
          Magnitude threshold, m
        </text>
        <text
          className="plot-axis-title"
          textAnchor="middle"
          transform={`translate(18 ${
            (frequencyMargin.top + height - frequencyMargin.bottom) / 2
          }) rotate(-90)`}
        >
          Cumulative events · log scale
        </text>
      </svg>
      <figcaption>
        <span>
          <i className="key-observed" /> Observed count
        </span>
        <span>
          <i className="key-fit" /> Descriptive fit
        </span>
      </figcaption>
    </figure>
  );
};

export const ImpactScatter = ({ events }: { events: EarthquakeEvent[] }) => {
  const width = 760;
  const height = 420;
  const maximumFelt = Math.max(1, ...events.map((event) => event.felt ?? 0));
  const x = scaleLinear().domain([2.4, 7.1]).range([
    impactMargin.left,
    width - impactMargin.right,
  ]);
  const y = scaleSymlog().constant(1).domain([0, maximumFelt]).range([
    height - impactMargin.bottom,
    impactMargin.top,
  ]);
  const mostFelt = events.reduce<EarthquakeEvent | undefined>(
    (current, event) =>
      !current || (event.felt ?? 0) > (current.felt ?? 0) ? event : current,
    undefined,
  );
  const yTicks = impactYTickCandidates.filter((tick) =>
    tick <= maximumFelt * 1.1
  );

  return (
    <figure className="impact-figure">
      <svg
        aria-label="Earthquake magnitude compared with felt reports for every event in the weekly catalog"
        role="img"
        viewBox={`0 0 ${width} ${height}`}
      >
        <desc>
          Each point is one event. Horizontal position shows magnitude and
          vertical position shows felt reports on a symmetric logarithmic scale.
          The most-reported event is labeled.
        </desc>
        {yTicks.map((tick) => (
          <g key={tick}>
            <line
              className="plot-gridline"
              x1={impactMargin.left}
              x2={width - impactMargin.right}
              y1={y(tick)}
              y2={y(tick)}
            />
            <text
              className="plot-tick"
              textAnchor="end"
              x={impactMargin.left - 14}
              y={y(tick) + 5}
            >
              {integer.format(tick)}
            </text>
          </g>
        ))}
        {magnitudeTicks.map((tick) => (
          <text
            className="plot-tick"
            key={tick}
            textAnchor="middle"
            x={x(tick)}
            y={height - impactMargin.bottom + 28}
          >
            {tick.toFixed(1)}
          </text>
        ))}
        <line
          className="plot-axis"
          x1={impactMargin.left}
          x2={impactMargin.left}
          y1={impactMargin.top}
          y2={height - impactMargin.bottom}
        />
        <line
          className="plot-axis"
          x1={impactMargin.left}
          x2={width - impactMargin.right}
          y1={height - impactMargin.bottom}
          y2={height - impactMargin.bottom}
        />
        {events.map((event) => (
          <circle
            className={`impact-point${
              event.tsunami ? " impact-point-alert" : ""
            }${event.id === mostFelt?.id ? " impact-point-lead" : ""}`}
            cx={x(event.magnitude)}
            cy={y(event.felt ?? 0)}
            key={event.id}
            r={event.magnitude >= 6 ? 5.5 : 3.1}
          >
            <title>
              M{event.magnitude.toFixed(1)} · {event.felt ?? 0} felt reports ·
              {event.place}
            </title>
          </circle>
        ))}
        {mostFelt
          ? (
            <g className="impact-annotation">
              <line
                x1={x(mostFelt.magnitude)}
                x2={x(mostFelt.magnitude) - 62}
                y1={y(mostFelt.felt ?? 0)}
                y2={y(mostFelt.felt ?? 0) + 42}
              />
              <text
                textAnchor="end"
                x={x(mostFelt.magnitude) - 68}
                y={y(mostFelt.felt ?? 0) + 48}
              >
                {integer.format(mostFelt.felt ?? 0)} reports
              </text>
            </g>
          )
          : null}
        <text
          className="plot-axis-title"
          textAnchor="middle"
          x={(impactMargin.left + width - impactMargin.right) / 2}
          y={height - 9}
        >
          Magnitude
        </text>
        <text
          className="plot-axis-title"
          textAnchor="middle"
          transform={`translate(18 ${
            (impactMargin.top + height - impactMargin.bottom) / 2
          }) rotate(-90)`}
        >
          Felt reports · symlog scale
        </text>
      </svg>
      <figcaption>
        One point per source record · orange marks carry a tsunami flag
      </figcaption>
    </figure>
  );
};
