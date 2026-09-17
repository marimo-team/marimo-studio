export type ErrorCase = {
  date: unknown;
  Temperature: number;
  Humidity: number;
  Light: number;
  CO2: number;
  Occupancy: number;
  score: number;
  predicted: number;
  outcome: string;
};

const timestamp = new Intl.DateTimeFormat("en", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});
const visibleErrors = 14;

const formatTime = (value: unknown) => {
  const parsed = value instanceof Date
    ? value
    : new Date(typeof value === "number" ? value : String(value));
  return Number.isNaN(parsed.getTime())
    ? String(value ?? "…")
    : timestamp.format(parsed);
};

export const ErrorEvidence = ({
  rows,
  total,
}: {
  rows: readonly ErrorCase[];
  total?: number;
}) => (
  <section className="error-section" aria-labelledby="errors-heading">
    <div className="panel-heading">
      <div>
        <p className="section-index">04 / Error evidence</p>
        <h2 id="errors-heading">Misclassified training readings</h2>
      </div>
      <p>
        Showing {Math.min(rows.length, visibleErrors)} sampled readings from
        {" "}
        {total ?? rows.length} errors.
      </p>
    </div>
    <div
      className="table-scroll"
      aria-label="Scrollable misclassified training readings"
      role="region"
      tabIndex={0}
    >
      <table className="error-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Outcome</th>
            <th>Score</th>
            <th>Observed</th>
            <th>Predicted</th>
            <th>Temp °C</th>
            <th>RH %</th>
            <th>Light lx</th>
            <th>CO₂ ppm</th>
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, visibleErrors).map((row) => (
            <tr
              key={String(row.date)}
              data-marimo-lens-inputs="analysis-data"
              data-marimo-lens-label={formatTime(row.date)}
            >
              <td>
                {formatTime(row.date)}
              </td>
              <td>
                <span className="outcome">{row.outcome}</span>
              </td>
              <td>
                {row.score.toFixed(3)}
              </td>
              <td>{row.Occupancy ? "Occupied" : "Empty"}</td>
              <td>{row.predicted ? "Occupied" : "Empty"}</td>
              <td>{row.Temperature.toFixed(1)}</td>
              <td>{row.Humidity.toFixed(1)}</td>
              <td>{row.Light.toFixed(0)}</td>
              <td>{row.CO2.toFixed(0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0
        ? <p className="empty-state">No sampled errors at this threshold.</p>
        : null}
    </div>
  </section>
);
