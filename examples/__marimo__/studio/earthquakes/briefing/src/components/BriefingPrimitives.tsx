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
}) => (
  <div
    className={`activity-chart${compact ? " activity-chart-compact" : ""}`}
    data-id="weekly-tempo-chart"
    aria-label="Earthquake events by day"
  >
    {activity.map((row) => {
      const key = String(row.day);
      const isPeak = key === peakKey;
      return (
        <div
          className={`activity-column${isPeak ? " activity-column-peak" : ""}`}
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
  </div>
);
