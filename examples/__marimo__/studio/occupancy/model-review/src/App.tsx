/// <reference path="./marimo-studio.d.ts" />

import { type ErrorCase, ErrorEvidence } from "./components/ErrorEvidence.tsx";
import {
  formatRate,
  ThresholdCurve,
  type ThresholdMetric,
} from "./components/ThresholdCurve.tsx";
import { type MarimoTable, useMarimoValue } from "./lib/use-marimo-value.ts";

const Metric = ({ label, value }: { label: string; value?: string }) => (
  <article className="metric">
    <span>{label}</span>
    <strong>{value ?? "…"}</strong>
  </article>
);

const ConfusionCounts = ({ summary }: { summary?: ThresholdMetric }) => (
  <article
    className="panel confusion-panel"
    aria-labelledby="confusion-heading"
  >
    <div className="panel-heading">
      <div>
        <p className="section-index">03 / Classification</p>
        <h2 id="confusion-heading">Confusion counts</h2>
      </div>
    </div>
    <table className="confusion-table">
      <caption>Observed occupancy by predicted occupancy</caption>
      <thead>
        <tr>
          <th>Observed</th>
          <th>Predicted occupied</th>
          <th>Predicted empty</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <th>Occupied</th>
          <td>
            <span>True positive</span>
            <strong>{summary?.true_positive ?? "…"}</strong>
          </td>
          <td className="error-count">
            <span>False negative</span>
            <strong>{summary?.false_negative ?? "…"}</strong>
          </td>
        </tr>
        <tr>
          <th>Empty</th>
          <td className="error-count">
            <span>False positive</span>
            <strong>{summary?.false_positive ?? "…"}</strong>
          </td>
          <td>
            <span>True negative</span>
            <strong>{summary?.true_negative ?? "…"}</strong>
          </td>
        </tr>
      </tbody>
    </table>
  </article>
);

export const App = () => {
  const metrics = useMarimoValue<MarimoTable<ThresholdMetric>>(
    "threshold_metrics",
  );
  const summary = useMarimoValue<ThresholdMetric>("model_summary");
  const errors = useMarimoValue<MarimoTable<ErrorCase>>("error_cases");
  const curve = metrics.value?.toArray() ?? [];
  const errorRows = errors.value?.toArray() ?? [];
  const unavailable = metrics.error || summary.error || errors.error;
  const loading = !unavailable && (metrics.value === undefined ||
    summary.value === undefined ||
    errors.value === undefined);

  return (
    <>
      <span
        ref={metrics.hostRef}
        aria-hidden="true"
        hidden
        mo-value="threshold_metrics"
      />
      <span
        ref={summary.hostRef}
        aria-hidden="true"
        hidden
        mo-value="model_summary"
      />
      <span
        ref={errors.hostRef}
        aria-hidden="true"
        hidden
        mo-value="error_cases"
      />

      <main className="review" aria-busy={loading}>
        {loading
          ? (
            <div className="review-loader" role="status">
              <span className="review-loader-sheet" aria-hidden="true">
                <i />
                <i />
                <i />
                <i />
              </span>
              Preparing model evidence
            </div>
          )
          : null}
        <header className="review-header">
          <div>
            <p className="eyebrow">Building occupancy · Training review</p>
            <h1>Threshold behavior and training errors</h1>
          </div>
          <p className="method-note">
            Transparent score: 70% normalized light and 30% normalized CO₂. The
            selected operating point is shown against the full threshold sweep.
          </p>
        </header>

        {unavailable
          ? (
            <p className="data-status" role="alert">
              Model results could not be loaded. Reload the page to retry.
            </p>
          )
          : null}

        <section className="control-strip" aria-labelledby="threshold-heading">
          <div>
            <p className="section-index">01 / Operating point</p>
            <h2 id="threshold-heading">Choose the occupancy threshold</h2>
          </div>
          <marimo-cell name="threshold_control" />
        </section>

        <section className="metric-grid" aria-label="Current threshold metrics">
          <Metric
            label="Threshold"
            value={summary.value?.threshold.toFixed(2)}
          />
          <Metric
            label="In-sample accuracy"
            value={summary.value && formatRate(summary.value.accuracy)}
          />
          <Metric
            label="In-sample precision"
            value={summary.value && formatRate(summary.value.precision)}
          />
          <Metric
            label="In-sample recall"
            value={summary.value && formatRate(summary.value.recall)}
          />
        </section>

        <section className="analysis-grid">
          <article
            className="panel curve-panel"
            aria-labelledby="curve-heading"
          >
            <div className="panel-heading">
              <div>
                <p className="section-index">02 / Threshold sweep</p>
                <h2 id="curve-heading">Metric curve</h2>
              </div>
              <p>The vertical marker shows the selected threshold.</p>
            </div>
            <ThresholdCurve
              current={summary.value?.threshold}
              metrics={curve}
            />
          </article>

          <ConfusionCounts summary={summary.value} />
        </section>

        <ErrorEvidence
          rows={errorRows}
          total={summary.value
            ? summary.value.false_positive + summary.value.false_negative
            : undefined}
        />
        <footer className="source-note">
          Source:{"  "}
          <a
            href="https://doi.org/10.24432/C5X01N"
            target="_blank"
            rel="noreferrer"
          >
            Luis Candanedo, UCI Occupancy Detection training split
          </a>{" "}
          ·{"  "}
          <a
            href="https://creativecommons.org/licenses/by/4.0/"
            target="_blank"
            rel="noreferrer"
          >
            CC BY 4.0
          </a>
        </footer>
      </main>
    </>
  );
};
