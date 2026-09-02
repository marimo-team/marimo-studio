// @deno-types="npm:@types/d3-geo@3.1.0"
import { geoEqualEarth, geoGraticule10, geoPath } from "d3-geo";
// @deno-types="npm:@types/d3-scale@4.0.9"
import { scaleLinear, scaleSqrt } from "d3-scale";
// @deno-types="npm:@types/d3-shape@3.2.0"
import { arc } from "d3-shape";
import { type StrongEvent } from "../briefing-data.ts";

const sphere = { type: "Sphere" } as const;

export const EventGlobe = ({ events }: { events: StrongEvent[] }) => {
  const width = 560;
  const height = 270;
  const projection = geoEqualEarth().fitExtent(
    [[12, 12], [width - 12, height - 12]],
    sphere,
  );
  const path = geoPath(projection);
  const radius = scaleSqrt()
    .domain([5.5, Math.max(7, ...events.map((event) => event.magnitude))])
    .range([6, 10]);

  return (
    <figure className="event-globe">
      <svg
        aria-label="Global positions of the five strongest earthquakes"
        role="img"
        viewBox={`0 0 ${width} ${height}`}
      >
        <path className="globe-sphere" d={path(sphere) ?? undefined} />
        <path
          className="globe-graticule"
          d={path(geoGraticule10()) ?? undefined}
        />
        {events.map((event, index) => ({ event, index })).toReversed().map((
          { event, index },
        ) => {
          const point = projection([event.longitude, event.latitude]);
          if (!point) return null;
          const [x, y] = point;
          return (
            <g
              className={[
                "event-point",
                index === 0 ? "event-point-lead" : "",
                event.tsunami ? "event-point-alert" : "",
              ].filter(Boolean).join(" ")}
              data-id={`event-point-${event.id}`}
              key={event.id}
              transform={`translate(${x}, ${y})`}
            >
              <title>
                {index + 1}. M{event.magnitude.toFixed(1)} · {event.place}
              </title>
              {index === 0
                ? (
                  <circle
                    className="event-point-lead-ring"
                    r={radius(event.magnitude) + 7}
                  />
                )
                : null}
              <circle
                className="event-point-halo"
                r={radius(event.magnitude) + 3}
              />
              <circle r={radius(event.magnitude)} />
              {index === 0 || event.tsunami
                ? (
                  <text
                    className="event-point-label"
                    dy="-0.7em"
                    textAnchor={x > width * 0.72 ? "end" : "start"}
                    x={x > width * 0.72
                      ? -(radius(event.magnitude) + 7)
                      : radius(event.magnitude) + 7}
                  >
                    M{event.magnitude.toFixed(1)}
                  </text>
                )
                : null}
            </g>
          );
        })}
      </svg>
      <figcaption>Priority event locations · weekly sequence</figcaption>
    </figure>
  );
};

export const MagnitudeLadder = ({ events }: { events: StrongEvent[] }) => {
  const width = 520;
  const height = 90;
  const minimum = Math.floor(
    Math.min(...events.map((event) => event.magnitude), 5.5) * 2,
  ) / 2;
  const maximum = Math.ceil(
    Math.max(...events.map((event) => event.magnitude), 7) * 2,
  ) / 2;
  const x = scaleLinear().domain([minimum, maximum]).range([24, width - 24]);

  return (
    <svg
      aria-label="Magnitude scale for the five strongest earthquakes"
      className="magnitude-ladder"
      role="img"
      viewBox={`0 0 ${width} ${height}`}
    >
      <line
        className="magnitude-axis"
        x1="24"
        x2={width - 24}
        y1="45"
        y2="45"
      />
      {x.ticks(4).map((tick) => (
        <g key={tick} transform={`translate(${x(tick)}, 45)`}>
          <line className="magnitude-tick" y1="-5" y2="5" />
          <text className="magnitude-label" dy="24" textAnchor="middle">
            M{tick.toFixed(1)}
          </text>
        </g>
      ))}
      {events.map((event, index) => (
        <g
          className={event.tsunami
            ? "magnitude-point magnitude-point-alert"
            : "magnitude-point"}
          data-id={`magnitude-point-${event.id}`}
          key={event.id}
          transform={`translate(${x(event.magnitude)}, 45)`}
        >
          <circle r={index === 0 ? 13 : 10} />
          <text dy="0.34em" textAnchor="middle">{index + 1}</text>
        </g>
      ))}
    </svg>
  );
};

export const ScopeGauge = (
  { selected, total }: { selected: number; total: number },
) => {
  const ratio = total > 0 ? Math.min(1, Math.max(0, selected / total)) : 0;
  const ring = arc();
  const background = ring({
    innerRadius: 31,
    outerRadius: 40,
    startAngle: 0,
    endAngle: Math.PI * 2,
  });
  const foreground = ring({
    innerRadius: 31,
    outerRadius: 40,
    startAngle: 0,
    endAngle: ratio * Math.PI * 2,
  });

  return (
    <div className="scope-gauge">
      <svg aria-hidden="true" viewBox="0 0 96 96">
        <g transform="translate(48, 48)">
          <path className="scope-ring-background" d={background ?? undefined} />
          <path className="scope-ring-foreground" d={foreground ?? undefined} />
        </g>
        <text x="48" y="45" textAnchor="middle">
          {Math.round(ratio * 100)}%
        </text>
        <text className="scope-gauge-label" x="48" y="59" textAnchor="middle">
          RETAINED
        </text>
      </svg>
    </div>
  );
};
