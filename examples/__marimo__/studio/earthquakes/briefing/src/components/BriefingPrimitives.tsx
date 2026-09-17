// @deno-types="npm:@types/d3-scale@4.0.9"
import { scaleLinear } from "d3-scale";
// @deno-types="npm:@types/d3-shape@3.2.0"
import { curveMonotoneX, line } from "d3-shape";
import { type DailyActivity, formatDay } from "../briefing-data.ts";

export const Metric = ({
  label,
  value,
  detail,
}: {
  detail?: string;
  label: string;
  value: number | string;
}) => (
  <div className="metric" data-marimo-lens-inputs="analysis-data">
    <span>{label}</span>
    <strong>{value}</strong>
    {detail ? <small>{detail}</small> : null}
  </div>
);

export const ActivityBars = ({
  activity,
  compact = false,
  maximum,
  peakKey,
}: {
  activity: DailyActivity[];
  compact?: boolean;
  maximum: number;
  peakKey?: string;
}) => {
  const magnitude = scaleLinear()
    .domain([
      2.5,
      Math.max(3, ...activity.map((row) => row.maximum_magnitude)),
    ])
    .range([92, 10]);
  const x = (index: number) => ((index + 0.5) / activity.length) * 100;
  const magnitudePath = line<DailyActivity>()
    .x((_, index) => x(index))
    .y((row) => magnitude(row.maximum_magnitude))
    .curve(curveMonotoneX)(activity);
  const maximumMagnitude = Math.max(
    0,
    ...activity.map((row) => row.maximum_magnitude),
  );

  return (
    <figure
      className={`activity-chart${compact ? " activity-chart-compact" : ""}`}
      data-id="weekly-tempo-chart"
      data-marimo-lens-inputs="analysis-data"
      aria-label="Daily earthquake count shown as bars and daily maximum magnitude shown as a line"
      role="img"
    >
      <span hidden mo-value="seismic_analysis.activity" />
      <div className="activity-plot">
        {activity.map((row) => {
          const key = String(row.day);
          const isPeak = key === peakKey;
          return (
            <div
              className={`activity-column${
                isPeak ? " activity-column-peak" : ""
              }`}
              data-id={`tempo-column-${key}`}
              key={key}
            >
              <span
                className="activity-bar"
                data-id={`tempo-bar-${key}`}
                style={{ height: `${(row.events / maximum) * 100}%` }}
              >
                <span className="activity-value">
                  {row.events}
                </span>
              </span>
              <span className="activity-label">{formatDay(row.day)}</span>
            </div>
          );
        })}
        <svg
          aria-hidden="true"
          className="activity-magnitude"
          preserveAspectRatio="none"
          viewBox="0 0 100 100"
        >
          <path d={magnitudePath ?? undefined} />
        </svg>
        <span className="activity-magnitude-points" aria-hidden="true">
          {activity.map((row, index) => (
            <i
              className={row.maximum_magnitude === maximumMagnitude
                ? "activity-magnitude-point activity-magnitude-peak"
                : "activity-magnitude-point"}
              data-id={`magnitude-mark-${String(row.day)}`}
              key={String(row.day)}
              style={{
                left: `${x(index)}%`,
                top: `${magnitude(row.maximum_magnitude)}%`,
              }}
            >
            </i>
          ))}
        </span>
      </div>
      <figcaption>
        <span>
          <i className="key-bar" /> Recorded events
        </span>
        <span>
          <i className="key-line" /> Maximum magnitude
        </span>
      </figcaption>
      <span className="sr-only">
        {activity.map((row) =>
          `${formatDay(row.day)}: ${row.events} events, maximum magnitude ${
            row.maximum_magnitude.toFixed(1)
          }.`
        ).join(" ")}
      </span>
    </figure>
  );
};
