// @deno-types="npm:@types/d3-scale@4.0.9"
import { scaleLinear } from "d3-scale";
// @deno-types="npm:@types/d3-shape@3.2.0"
import { curveMonotoneX, line } from "d3-shape";
import { type DailyActivity, formatDay } from "../briefing-data.ts";

export const Metric = ({
  label,
  value,
}: {
  label: string;
  value: number | string;
}) => (
  <div className="metric">
    <strong>{value}</strong>
    <span>{label}</span>
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
      0,
      Math.max(1, ...activity.map((row) => row.maximum_magnitude)),
    ])
    .range([94, 8]);
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
    <div
      className={`activity-chart${compact ? " activity-chart-compact" : ""}`}
      data-id="weekly-tempo-chart"
      aria-label="Earthquake events and maximum magnitude by day"
    >
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
            <span className="activity-value">{row.events}</span>
            <span
              className="activity-bar"
              data-id={`tempo-bar-${key}`}
              style={{ height: `${(row.events / maximum) * 100}%` }}
            />
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
        {activity.map((row, index) => (
          <line
            className={row.maximum_magnitude === maximumMagnitude
              ? "activity-magnitude-peak"
              : undefined}
            data-id={`magnitude-mark-${String(row.day)}`}
            key={String(row.day)}
            x1={x(index)}
            x2={x(index)}
            y1={magnitude(row.maximum_magnitude) - 1.8}
            y2={magnitude(row.maximum_magnitude) + 1.8}
          />
        ))}
      </svg>
      <span className="activity-line-key" aria-hidden="true">
        <i /> Daily max magnitude
      </span>
    </div>
  );
};
